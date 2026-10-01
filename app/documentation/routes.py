"""Routes pour la page de documentation interne."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.core.dependencies import UtilisateurCourant
from app.core.templating import rendre

router = APIRouter(tags=["Documentation"])


@router.get("/documentation", response_class=HTMLResponse, summary="Documentation utilisateur")
async def documentation_index(request: Request, utilisateur: UtilisateurCourant) -> HTMLResponse:
    """Affiche la documentation expliquant les éléments du tableau de bord et de l'application."""
    return rendre(
        request,
        "documentation/index.html",
        {
            "page_active": "/documentation",
        },
    )
