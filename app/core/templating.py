"""Moteur de templates Jinja2, messages flash et helper de rendu `rendre(...)`."""

from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config import DOSSIER_APP, settings
from app.core.security import NOM_CHAMP_CSRF, REGLES_MOT_DE_PASSE, obtenir_jeton_csrf
from app.utilisateur.model import Role

templates = Jinja2Templates(directory=DOSSIER_APP / "templates")

# ---------------------------------------------------------------------------
# Messages flash (stockés en session, affichés une seule fois)
# ---------------------------------------------------------------------------

CategorieFlash = Literal["success", "danger", "warning", "info"]
CLE_SESSION_FLASH = "_flashs"


def flash(request: Request, message: str, categorie: CategorieFlash = "success") -> None:
    """Ajoute un message à afficher sur la prochaine page rendue."""
    messages = list(request.session.get(CLE_SESSION_FLASH, []))
    messages.append({"categorie": categorie, "message": message})
    request.session[CLE_SESSION_FLASH] = messages


def recuperer_flashs(request: Request) -> list[dict[str, str]]:
    """Retourne et efface les messages flash en attente."""
    if "session" not in request.scope:
        return []
    return list(request.session.pop(CLE_SESSION_FLASH, []))


# ---------------------------------------------------------------------------
# Filtres et fonctions Jinja
# ---------------------------------------------------------------------------


def _en_utc(valeur: datetime) -> datetime:
    return valeur.astimezone(UTC) if valeur.tzinfo else valeur


def filtre_date_heure(valeur: datetime | None) -> str:
    """« 18/09/2026 14:05 » (UTC)."""
    return _en_utc(valeur).strftime("%d/%m/%Y %H:%M") if valeur else ""


def filtre_date(valeur: date | datetime | None) -> str:
    """« 18/09/2026 »."""
    if not valeur:
        return ""
    if isinstance(valeur, datetime):
        valeur = _en_utc(valeur)
    return valeur.strftime("%d/%m/%Y")


def filtre_oui_non(valeur: object) -> str:
    return "Oui" if valeur else "Non"


def static(chemin: str) -> str:
    """URL relative d'un fichier statique (évite les URL absolues http/https erronées derrière un proxy)."""
    return "/static/" + chemin.lstrip("/")


def lien_menu_actif(chemin: str, urls: Iterable[str]) -> str | None:
    """URL du menu la plus spécifique correspondant au chemin courant."""
    correspondances = [u for u in urls if chemin == u or chemin.startswith(u.rstrip("/") + "/")]
    return max(correspondances, key=len, default=None)


templates.env.globals.update(
    app_name=settings.APP_NAME,
    static=static,
    Role=Role,
    lien_menu_actif=lien_menu_actif,
    REGLES_MOT_DE_PASSE=REGLES_MOT_DE_PASSE,
    NOM_CHAMP_CSRF=NOM_CHAMP_CSRF,
)
templates.env.filters.update(
    date_heure=filtre_date_heure,
    date=filtre_date,
    oui_non=filtre_oui_non,
)


# ---------------------------------------------------------------------------
# Rendu
# ---------------------------------------------------------------------------


def rendre(
    request: Request,
    template: str,
    contexte: Mapping[str, Any] | None = None,
    *,
    status_code: int = 200,
    page_active: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> HTMLResponse:
    """Rend un template en injectant : request, utilisateur, csrf_token, flashs, page_active, annee.

    - `utilisateur` : request.state.utilisateur (posé par les dépendances d'authentification) ou None.
    - `page_active` : URL du lien de menu à mettre en évidence (déduite du chemin si absente).
    """
    donnees: dict[str, Any] = {
        "request": request,
        "utilisateur": getattr(request.state, "utilisateur", None),
        "csrf_token": obtenir_jeton_csrf(request),
        "flashs": recuperer_flashs(request),
        "page_active": page_active,
        "annee": datetime.now(UTC).year,
    }
    if contexte:
        donnees.update(contexte)
    return templates.TemplateResponse(
        request, template, donnees, status_code=status_code, headers=dict(headers) if headers else None
    )
