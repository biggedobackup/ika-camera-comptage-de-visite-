"""Routes du module tableau_de_bord."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.core.dependencies import DbSession, UtilisateurCourant
from app.core.templating import rendre
from app.historique.services import ACTIONS_ALERTE, libelle_module
from app.tableau_de_bord.services import tableau_de_bord_gestion, voit_vue_gestion

router = APIRouter(tags=["Tableau de bord"])


@router.get("/tableau-de-bord", response_class=HTMLResponse, summary="Tableau de bord")
async def index(request: Request, db: DbSession, utilisateur: UtilisateurCourant) -> HTMLResponse:
    """ADMIN / MANAGER : indicateurs + dernières activités. UTILISATEUR : vue simple de son compte."""
    contexte: dict[str, object] = {"vue_gestion": voit_vue_gestion(utilisateur)}
    if contexte["vue_gestion"]:
        contexte.update(
            gestion=await tableau_de_bord_gestion(db),
            libelle_module=libelle_module,
            actions_alerte=ACTIONS_ALERTE,
        )
    return rendre(request, "tableau_de_bord/index.html", contexte)
