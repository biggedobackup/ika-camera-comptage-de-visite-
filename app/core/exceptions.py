"""Exceptions applicatives et gestionnaires globaux (pages d'erreur personnalisées)."""

import logging
from http import HTTPStatus
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.exc import InterfaceError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.security import entetes_securite, supprimer_cookie_jeton
from app.core.templating import flash, rendre

logger = logging.getLogger("app.erreurs")

PAGES_ERREUR = {400, 401, 403, 404, 429, 500, 503}

TITRES = {
    400: "Requête invalide",
    401: "Authentification requise",
    403: "Accès refusé",
    404: "Page introuvable",
    405: "Méthode non autorisée",
    429: "Trop de tentatives",
    500: "Erreur interne du serveur",
    503: "Service momentanément indisponible",
}

MESSAGES = {
    400: "La requête envoyée est invalide ou incomplète. Vérifiez les informations saisies puis réessayez.",
    401: "Vous devez être connecté pour accéder à cette page.",
    403: "Vous n'avez pas les droits nécessaires pour accéder à cette page ou effectuer cette action.",
    404: "La page demandée n'existe pas ou a été déplacée. Vérifiez l'adresse saisie.",
    405: "Cette action n'est pas autorisée à cette adresse.",
    429: "Trop de tentatives en peu de temps. Veuillez patienter avant de réessayer.",
    500: "Une erreur inattendue s'est produite. Elle a été enregistrée ; veuillez réessayer dans quelques instants.",
    503: "Le service est momentanément indisponible. Veuillez réessayer dans quelques instants.",
}


class AuthentificationRequise(Exception):
    """Levée par les dépendances d'authentification : redirige vers /connexion avec un message."""

    def __init__(self, message: str = "Veuillez vous connecter pour accéder à cette page.") -> None:
        super().__init__(message)
        self.message = message


def _message(code: int, detail: object) -> str:
    """Message à afficher : le détail s'il a été rédigé pour l'utilisateur, sinon le message par défaut."""
    try:
        phrase = HTTPStatus(code).phrase
    except ValueError:
        phrase = ""
    if isinstance(detail, str) and detail and detail != phrase:
        return detail
    return MESSAGES.get(code) or MESSAGES[500 if code >= 500 else 400]


def page_erreur(
    request: Request,
    code: int,
    message: str | None = None,
    headers: dict[str, str] | None = None,
) -> Response:
    """Rend la page d'erreur personnalisée correspondant au code HTTP."""
    gabarit = code if code in PAGES_ERREUR else (500 if code >= 500 else 400)
    contexte = {
        "code": code,
        "titre": TITRES.get(code) or TITRES[gabarit],
        "message": message or _message(code, None),
        "retry_after": (headers or {}).get("Retry-After"),
    }
    try:
        return rendre(request, f"erreurs/{gabarit}.html", contexte, status_code=code, headers=headers)
    except Exception:
        # Dernier recours (ex. utilisateur courant inutilisable) : page sans menu, puis HTML minimal.
        logger.exception("Échec du rendu de la page d'erreur %s", code)
        request.state.utilisateur = None
        try:
            return rendre(request, f"erreurs/{gabarit}.html", contexte, status_code=code, headers=headers)
        except Exception:
            return HTMLResponse(
                f"<!doctype html><html lang=\"fr\"><meta charset=\"utf-8\"><title>Erreur {code}</title>"
                f"<p>Erreur {code}. Veuillez réessayer plus tard.</p></html>",
                status_code=code,
                headers=headers,
            )


async def gerer_authentification_requise(request: Request, exc: AuthentificationRequise) -> Response:
    """Page protégée sans authentification valide → /connexion (avec retour à la page demandée)."""
    flash(request, exc.message, "warning")
    url = "/connexion"
    if request.method == "GET":
        chemin = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        url += "?" + urlencode({"suivant": chemin})
    response = RedirectResponse(url, status_code=303)
    supprimer_cookie_jeton(response)
    return response


async def gerer_http_exception(request: Request, exc: StarletteHTTPException) -> Response:
    headers = dict(exc.headers) if exc.headers else None
    return page_erreur(request, exc.status_code, _message(exc.status_code, exc.detail), headers)


async def gerer_validation(request: Request, exc: RequestValidationError) -> Response:
    """Paramètre de chemin invalide (ex. identifiant mal formé) → 404 ; autre donnée invalide → 400."""
    erreurs = exc.errors()
    if erreurs and all(e.get("loc", ("",))[0] == "path" for e in erreurs):
        return page_erreur(request, 404)
    return page_erreur(request, 400)


async def gerer_service_indisponible(request: Request, exc: Exception) -> Response:
    """Base de données (ou autre ressource réseau) injoignable → 503."""
    logger.error("Service indisponible sur %s %s : %s: %s", request.method, request.url.path,
                 exc.__class__.__name__, exc)
    return page_erreur(request, 503, headers={"Retry-After": "30"})


async def gerer_exception(request: Request, exc: Exception) -> Response:
    """Erreur non gérée : journalisée avec sa trace, page 500 sans aucun détail technique."""
    logger.exception("Erreur non gérée sur %s %s", request.method, request.url.path, exc_info=exc)
    response = page_erreur(request, 500)
    # Ce gestionnaire s'exécute hors des middlewares : on ajoute les en-têtes de sécurité ici.
    for nom, valeur in entetes_securite(request.url.path).items():
        response.headers[nom] = valeur
    return response


def enregistrer_gestionnaires(app: FastAPI) -> None:
    """Branche tous les gestionnaires d'exceptions sur l'application."""
    app.add_exception_handler(AuthentificationRequise, gerer_authentification_requise)
    app.add_exception_handler(StarletteHTTPException, gerer_http_exception)
    app.add_exception_handler(RequestValidationError, gerer_validation)
    app.add_exception_handler(OperationalError, gerer_service_indisponible)
    app.add_exception_handler(InterfaceError, gerer_service_indisponible)
    # asyncpg lève OSError (connexion refusée, délai dépassé) sans passer par SQLAlchemy.
    app.add_exception_handler(OSError, gerer_service_indisponible)
    app.add_exception_handler(Exception, gerer_exception)
