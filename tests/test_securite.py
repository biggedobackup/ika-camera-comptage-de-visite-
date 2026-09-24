"""En-têtes de sécurité, CSP, hôtes autorisés, CORS, CSRF, cookies et absence de code inline."""

import re

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import RACINE_PROJET, Settings
from app.core.security import CSP_STRICTE
from conftest import EMAIL_ADMIN, MOT_DE_PASSE, contenu, obtenir_csrf, se_connecter

ENTETES_ATTENDUS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def verifier_entetes(reponse: httpx.Response, csp: str = CSP_STRICTE) -> None:
    for nom, valeur in ENTETES_ATTENDUS.items():
        assert reponse.headers.get(nom) == valeur, nom
    assert reponse.headers.get("Content-Security-Policy") == csp


# ---------------------------------------------------------------------------
# En-têtes et CSP
# ---------------------------------------------------------------------------


def test_csp_stricte_sans_unsafe() -> None:
    assert "unsafe-inline" not in CSP_STRICTE
    assert "unsafe-eval" not in CSP_STRICTE
    for directive in ("default-src 'self'", "script-src 'self'", "style-src 'self'", "object-src 'none'",
                      "frame-ancestors 'none'", "form-action 'self'", "base-uri 'self'"):
        assert directive in CSP_STRICTE


@pytest.mark.parametrize(
    ("chemin", "statut"),
    [
        ("/connexion", 200),
        ("/", 303),
        ("/tableau-de-bord", 303),
        ("/page-inexistante", 404),
        ("/static/css/style.css", 200),
        ("/static/js/app.js", 200),
        ("/openapi.json", 200),
    ],
)
async def test_entetes_de_securite_sur_toutes_les_reponses(client: httpx.AsyncClient, chemin: str, statut: int) -> None:
    reponse = await client.get(chemin)
    assert reponse.status_code == statut
    verifier_entetes(reponse)


@pytest.mark.parametrize("chemin", ["/docs", "/redoc"])
async def test_csp_assouplie_limitee_a_la_documentation(client: httpx.AsyncClient, chemin: str) -> None:
    reponse = await client.get(chemin)
    assert reponse.status_code == 200
    csp = reponse.headers["Content-Security-Policy"]
    assert csp != CSP_STRICTE and "https://cdn.jsdelivr.net" in csp
    assert "unsafe-eval" not in csp
    assert reponse.headers["X-Frame-Options"] == "DENY"


async def test_hote_non_autorise_refuse(client: httpx.AsyncClient) -> None:
    reponse = await client.get("/connexion", headers={"Host": "attaquant.example"})
    assert reponse.status_code == 400
    verifier_entetes(reponse)


async def test_cors_restreint(client: httpx.AsyncClient) -> None:
    refusee = await client.get("/connexion", headers={"Origin": "https://attaquant.example"})
    assert "access-control-allow-origin" not in refusee.headers

    autorisee = await client.get("/connexion", headers={"Origin": "http://127.0.0.1:8000"})
    assert autorisee.headers.get("access-control-allow-origin") == "http://127.0.0.1:8000"

    preflight = await client.options(
        "/connexion",
        headers={"Origin": "https://attaquant.example", "Access-Control-Request-Method": "POST"},
    )
    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------


async def test_csrf_absent_refuse(client: httpx.AsyncClient, admin) -> None:
    await client.get("/connexion")
    reponse = await client.post("/connexion", data={"email": EMAIL_ADMIN, "mot_de_passe": MOT_DE_PASSE})
    assert reponse.status_code == 403
    assert "jeton de sécurité du formulaire est absent, invalide ou expiré" in contenu(reponse)
    assert "ika_jeton" not in client.cookies


async def test_csrf_invalide_refuse(client: httpx.AsyncClient, admin) -> None:
    await client.get("/connexion")
    reponse = await client.post(
        "/connexion", data={"csrf_token": "jeton-falsifie", "email": EMAIL_ADMIN, "mot_de_passe": MOT_DE_PASSE}
    )
    assert reponse.status_code == 403
    assert "ika_jeton" not in client.cookies


async def test_csrf_sans_session_refuse(client: httpx.AsyncClient) -> None:
    reponse = await client.post("/inscription", data={"csrf_token": "x" * 43})
    assert reponse.status_code == 403


async def test_csrf_requis_pour_la_deconnexion(client_admin: httpx.AsyncClient) -> None:
    reponse = await client_admin.post("/deconnexion")
    assert reponse.status_code == 403
    # Toujours connecté.
    assert (await client_admin.get("/tableau-de-bord")).status_code == 200


async def test_csrf_accepte_en_entete(client_admin: httpx.AsyncClient) -> None:
    jeton = await obtenir_csrf(client_admin, "/tableau-de-bord")
    reponse = await client_admin.post("/deconnexion", headers={"X-CSRF-Token": jeton})
    assert reponse.status_code == 303


async def test_tous_les_formulaires_post_ont_un_champ_csrf(client_admin: httpx.AsyncClient, admin) -> None:
    for chemin in ("/tableau-de-bord", "/profil", "/otp/configuration", "/utilisateurs", "/utilisateurs/ajouter",
                   f"/utilisateurs/{admin.id}", f"/utilisateurs/{admin.id}/modifier"):
        page = (await client_admin.get(chemin)).text
        formulaires = re.findall(r"<form[^>]*method=\"post\"[^>]*>(.*?)</form>", page, flags=re.S | re.I)
        assert formulaires, chemin
        for formulaire in formulaires:
            assert 'name="csrf_token"' in formulaire, chemin


# ---------------------------------------------------------------------------
# Cookies
# ---------------------------------------------------------------------------


async def test_cookies_httponly_et_samesite(client: httpx.AsyncClient, admin) -> None:
    reponse = await se_connecter(client, EMAIL_ADMIN)
    assert reponse.status_code == 303
    cookies = [valeur.lower() for valeur in reponse.headers.get_list("set-cookie")]
    jeton = next(c for c in cookies if c.startswith("ika_jeton="))
    session = next(c for c in cookies if c.startswith("ika_session="))
    for cookie in (jeton, session):
        assert "httponly" in cookie
        assert "samesite=lax" in cookie
        assert "path=/" in cookie


def _parametres(**valeurs: object) -> Settings:
    base = {"SECRET_KEY": "k" * 40, "DATABASE_URL": "postgresql+asyncpg://u@localhost/db", "APP_DEBUG": False}
    return Settings(_env_file=None, **{**base, **valeurs})


def test_cookie_secure_selon_l_environnement() -> None:
    assert _parametres(APP_ENV="production", COOKIE_SECURE=None).cookie_secure is True
    assert _parametres(APP_ENV="development", COOKIE_SECURE=None).cookie_secure is False
    assert _parametres(APP_ENV="development", COOKIE_SECURE=True).cookie_secure is True


def test_production_refuse_une_cle_par_defaut() -> None:
    with pytest.raises(ValidationError):
        _parametres(APP_ENV="production", SECRET_KEY="change-me-with-a-long-random-string")
    with pytest.raises(ValidationError):
        _parametres(APP_ENV="production", APP_DEBUG=True)


# ---------------------------------------------------------------------------
# Aucun CSS / JS inline (CSP sans unsafe-inline)
# ---------------------------------------------------------------------------

MOTIFS_INLINE = {
    "balise <style>": re.compile(r"<style\b", re.I),
    "attribut style": re.compile(r"\sstyle\s*=", re.I),
    "script inline": re.compile(r"<script\b(?![^>]*\bsrc=)[^>]*>", re.I),
    "gestionnaire on*": re.compile(r"<[^>]+\son[a-z]+\s*=", re.I),
}


def verifier_sans_inline(page: str, chemin: str) -> None:
    for nom, motif in MOTIFS_INLINE.items():
        assert not motif.search(page), f"{nom} trouvé dans {chemin}"


@pytest.mark.parametrize(
    "chemin", ["/connexion", "/inscription", "/mot-de-passe-oublie", "/mot-de-passe/reinitialiser", "/introuvable"]
)
async def test_pages_publiques_sans_code_inline(client: httpx.AsyncClient, chemin: str) -> None:
    verifier_sans_inline((await client.get(chemin)).text, chemin)


async def test_pages_connectees_sans_code_inline(client_admin: httpx.AsyncClient, admin) -> None:
    for chemin in ("/tableau-de-bord", "/profil", "/otp/configuration", "/utilisateurs", "/utilisateurs/ajouter",
                   f"/utilisateurs/{admin.id}", f"/utilisateurs/{admin.id}/modifier", "/historique"):
        reponse = await client_admin.get(chemin)
        assert reponse.status_code == 200, chemin
        verifier_sans_inline(reponse.text, chemin)


def test_feuille_de_style_sans_degrade() -> None:
    css = (RACINE_PROJET / "app" / "static" / "css" / "style.css").read_text(encoding="utf-8").lower()
    assert "gradient" not in css
    assert "#1270b8" in css and "#e51b35" in css
