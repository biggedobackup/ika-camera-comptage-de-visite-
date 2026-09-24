"""Pages d'erreur personnalisées (400, 401, 403, 404, 429, 500, 503) et gestion globale des exceptions."""

import logging
import uuid
from collections.abc import Iterator

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

from app.core.exceptions import TITRES
from app.main import app as application
from conftest import contenu

PREFIXE = "/test-erreurs"
MESSAGE_INTERNE = "détail interne à ne jamais afficher"


async def _lever_http(code: int) -> None:
    raise HTTPException(status_code=code)


async def _lever_exception() -> None:
    raise RuntimeError(MESSAGE_INTERNE)


async def _lever_base_indisponible() -> None:
    raise OperationalError("SELECT 1", {}, ConnectionRefusedError(MESSAGE_INTERNE))


async def _parametre_entier(nombre: int) -> dict[str, int]:
    return {"nombre": nombre}


@pytest.fixture
def routes_de_test() -> Iterator[None]:
    """Routes temporaires qui lèvent des erreurs (retirées après le test)."""
    avant = list(application.router.routes)
    application.add_api_route(PREFIXE + "/http/{code}", _lever_http)
    application.add_api_route(PREFIXE + "/exception", _lever_exception)
    application.add_api_route(PREFIXE + "/base-indisponible", _lever_base_indisponible)
    application.add_api_route(PREFIXE + "/parametre", _parametre_entier)
    yield
    application.router.routes[:] = avant


class Collecteur(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record)


@pytest.mark.parametrize("code", [400, 401, 403, 404, 429, 500, 503])
async def test_pages_d_erreur_personnalisees(client: httpx.AsyncClient, routes_de_test: None, code: int) -> None:
    reponse = await client.get(f"{PREFIXE}/http/{code}")
    assert reponse.status_code == code
    assert reponse.headers["content-type"].startswith("text/html")
    page = contenu(reponse)
    assert f"Erreur {code}" in page and TITRES[code] in page
    assert "Content-Security-Policy" in reponse.headers
    assert 'href="/static/css/style.css' in page  # page complète, stylée (anti-cache ?v= accepté)


async def test_404_page_inconnue(client: httpx.AsyncClient) -> None:
    reponse = await client.get("/cette-page-n-existe-pas")
    assert reponse.status_code == 404
    page = contenu(reponse)
    assert "Page introuvable" in page and "Aller à la page de connexion" in page


async def test_404_utilisateur_connecte_avec_menu(client_admin: httpx.AsyncClient) -> None:
    reponse = await client_admin.get(f"/utilisateurs/{uuid.uuid4()}")
    assert reponse.status_code == 404
    page = contenu(reponse)
    assert "Retour au tableau de bord" in page and 'class="offcanvas-lg offcanvas-start app-menu"' in page


async def test_405_methode_non_autorisee(client: httpx.AsyncClient) -> None:
    reponse = await client.delete("/connexion")
    assert reponse.status_code == 405
    assert "Cette action n'est pas autorisée à cette adresse." in contenu(reponse)


async def test_400_parametre_invalide(client: httpx.AsyncClient, routes_de_test: None) -> None:
    reponse = await client.get(f"{PREFIXE}/parametre?nombre=abc")
    assert reponse.status_code == 400
    assert "Requête invalide" in contenu(reponse)


async def test_500_sans_trace_technique_et_journalisee(client: httpx.AsyncClient, routes_de_test: None) -> None:
    collecteur = Collecteur()
    journal = logging.getLogger("app.erreurs")
    journal.addHandler(collecteur)
    try:
        reponse = await client.get(f"{PREFIXE}/exception")
    finally:
        journal.removeHandler(collecteur)
    assert reponse.status_code == 500
    page = contenu(reponse)
    assert "Erreur interne du serveur" in page
    assert MESSAGE_INTERNE not in page and "Traceback" not in page and "RuntimeError" not in page
    assert reponse.headers["Content-Security-Policy"] and reponse.headers["X-Frame-Options"] == "DENY"
    assert any(record.exc_info and MESSAGE_INTERNE in str(record.exc_info[1]) for record in collecteur.messages)


async def test_503_base_indisponible(client: httpx.AsyncClient, routes_de_test: None) -> None:
    reponse = await client.get(f"{PREFIXE}/base-indisponible")
    assert reponse.status_code == 503
    assert reponse.headers["Retry-After"] == "30"
    page = contenu(reponse)
    assert "Service momentanément indisponible" in page and MESSAGE_INTERNE not in page


async def test_401_redirige_les_pages_protegees(client: httpx.AsyncClient) -> None:
    reponse = await client.get("/profil")
    assert reponse.status_code == 303 and reponse.headers["location"] == "/connexion?suivant=%2Fprofil"
