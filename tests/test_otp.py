"""Double authentification TOTP : activation, secret chiffré en base, connexion en deux étapes,
limitation de débit et désactivation."""

import re
import time

import httpx
import pyotp
from sqlalchemy import update

from app.core.database import SessionLocal
from app.core.security import chiffrer_secret, dechiffrer_secret
from app.historique.model import ActionHistorique
from app.utilisateur.model import User
from conftest import (
    EMAIL_UTILISATEUR,
    MOT_DE_PASSE,
    contenu,
    entrees_historique,
    lire_compte,
    poster,
    se_connecter,
)


def code_faux(secret: str) -> str:
    """Un code à 6 chiffres différent des codes acceptés (fenêtre de ± 30 s)."""
    totp = pyotp.TOTP(secret)
    instant = time.time()
    valides = {totp.at(instant + decalage) for decalage in (-60, -30, 0, 30, 60)}
    return next(code for n in range(1_000_000) if (code := f"{n:06d}") not in valides)


async def activer_otp_en_base(email: str) -> str:
    """Active directement l'OTP d'un compte (secret chiffré) et retourne le secret en clair."""
    secret = pyotp.random_base32(length=32)
    async with SessionLocal() as db:
        await db.execute(
            update(User).where(User.email == email).values(otp_secret_chiffre=chiffrer_secret(secret), otp_active=True)
        )
        await db.commit()
    return secret


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------


async def test_activation_otp(client_utilisateur: httpx.AsyncClient) -> None:
    page = await client_utilisateur.get("/otp/configuration")
    assert page.status_code == 200
    assert page.headers["Cache-Control"] == "no-store"
    assert 'src="data:image/png;base64,' in page.text  # QR code en data: URI
    secret = re.search(r'<p class="code-secret[^"]*">([A-Z2-7 ]+)</p>', page.text).group(1).replace(" ", "")

    # Le QR code reste le même si la page est rechargée.
    assert secret in (await client_utilisateur.get("/otp/configuration")).text.replace(" ", "")

    refus = await poster(client_utilisateur, "/otp/configuration", {"code": code_faux(secret)}, page_csrf="/otp/configuration")
    assert refus.status_code == 400
    assert "Code de vérification incorrect ou expiré." in contenu(refus)
    assert not (await lire_compte(EMAIL_UTILISATEUR)).otp_active

    reponse = await poster(
        client_utilisateur, "/otp/configuration", {"code": pyotp.TOTP(secret).now()}, page_csrf="/otp/configuration"
    )
    assert reponse.status_code == 303
    assert "La double authentification est activée." in contenu(await client_utilisateur.get("/otp/configuration"))

    compte = await lire_compte(EMAIL_UTILISATEUR)
    assert compte.otp_active
    # Secret chiffré en base : jamais en clair, déchiffrable avec la clé de l'application.
    assert compte.otp_secret_chiffre and secret not in compte.otp_secret_chiffre
    assert dechiffrer_secret(compte.otp_secret_chiffre) == secret

    activations = await entrees_historique(ActionHistorique.OTP_ACTIVATION)
    assert len(activations) == 1
    for entree in await entrees_historique():
        assert secret not in str(entree.donnees_avant) + str(entree.donnees_apres) + entree.description


async def test_activation_otp_code_mal_forme(client_utilisateur: httpx.AsyncClient) -> None:
    reponse = await poster(client_utilisateur, "/otp/configuration", {"code": "12ab"}, page_csrf="/otp/configuration")
    assert reponse.status_code == 400
    assert "exactement 6 chiffres" in contenu(reponse)


async def test_desactivation_otp(client_utilisateur: httpx.AsyncClient) -> None:
    await activer_otp_en_base(EMAIL_UTILISATEUR)

    refus = await poster(
        client_utilisateur, "/otp/desactivation", {"mot_de_passe_actuel": "Faux#MotDePasse1"}, page_csrf="/otp/configuration"
    )
    assert refus.status_code == 400
    assert "Le mot de passe actuel est incorrect." in contenu(refus)
    assert (await lire_compte(EMAIL_UTILISATEUR)).otp_active

    reponse = await poster(
        client_utilisateur, "/otp/desactivation", {"mot_de_passe_actuel": MOT_DE_PASSE}, page_csrf="/otp/configuration"
    )
    assert reponse.status_code == 303
    compte = await lire_compte(EMAIL_UTILISATEUR)
    assert not compte.otp_active and compte.otp_secret_chiffre is None
    assert len(await entrees_historique(ActionHistorique.OTP_DESACTIVATION)) == 1


# ---------------------------------------------------------------------------
# Connexion avec OTP
# ---------------------------------------------------------------------------


async def test_connexion_avec_otp(client: httpx.AsyncClient, utilisateur_simple: User) -> None:
    secret = await activer_otp_en_base(EMAIL_UTILISATEUR)

    etape1 = await se_connecter(client, EMAIL_UTILISATEUR)
    assert etape1.status_code == 303 and etape1.headers["location"] == "/otp/verification"
    assert "ika_jeton" not in client.cookies  # aucun JWT avant le code OTP
    assert (await client.get("/tableau-de-bord")).status_code == 303

    page = await client.get("/otp/verification")
    assert page.status_code == 200 and "Vérification en deux étapes" in contenu(page)

    refus = await poster(client, "/otp/verification", {"code": code_faux(secret)})
    assert refus.status_code == 401
    assert "Code de vérification incorrect ou expiré." in contenu(refus)
    assert "ika_jeton" not in client.cookies

    reponse = await poster(client, "/otp/verification", {"code": pyotp.TOTP(secret).now()})
    assert reponse.status_code == 303 and reponse.headers["location"] == "/tableau-de-bord"
    assert "ika_jeton" in client.cookies
    assert (await client.get("/tableau-de-bord")).status_code == 200

    connexion = (await entrees_historique(ActionHistorique.CONNEXION))[0]
    assert "avec double authentification" in connexion.description
    assert (await lire_compte(EMAIL_UTILISATEUR)).tentatives_echouees == 0


async def test_verification_otp_sans_etape_en_cours(client: httpx.AsyncClient) -> None:
    reponse = await client.get("/otp/verification")
    assert reponse.status_code == 303 and reponse.headers["location"] == "/connexion"
    assert "Votre étape de vérification a expiré" in contenu(await client.get("/connexion"))


async def test_limitation_de_debit_otp(client: httpx.AsyncClient, utilisateur_simple: User) -> None:
    await activer_otp_en_base(EMAIL_UTILISATEUR)
    await se_connecter(client, EMAIL_UTILISATEUR)
    for _ in range(5):  # 5 tentatives par utilisateur sur 5 minutes
        assert (await poster(client, "/otp/verification", {"code": "abc"})).status_code == 400
    reponse = await poster(client, "/otp/verification", {"code": "abc"})
    assert reponse.status_code == 429
    assert int(reponse.headers["Retry-After"]) > 0
    assert "Trop de tentatives" in contenu(reponse)


async def test_codes_otp_faux_verrouillent_le_compte(client: httpx.AsyncClient, utilisateur_simple: User) -> None:
    secret = await activer_otp_en_base(EMAIL_UTILISATEUR)
    await se_connecter(client, EMAIL_UTILISATEUR)
    for _ in range(4):
        assert (await poster(client, "/otp/verification", {"code": code_faux(secret)})).status_code == 401
    reponse = await poster(client, "/otp/verification", {"code": code_faux(secret)})
    assert reponse.status_code == 303 and reponse.headers["location"] == "/connexion"
    assert "temporairement verrouillé" in contenu(await client.get("/connexion"))
    assert (await lire_compte(EMAIL_UTILISATEUR)).est_verrouille
