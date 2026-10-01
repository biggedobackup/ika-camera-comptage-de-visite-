"""Routes du module tableau_de_bord."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.camera.services import obtenir_cameras
from app.core.database import maintenant
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
        # Paramètres de filtre
        aujourdhui = maintenant().strftime("%Y-%m-%d")
        date_debut = (request.query_params.get("date_debut") or "").strip() or aujourdhui
        date_fin = (request.query_params.get("date_fin") or "").strip() or date_debut
        camera_sn = (request.query_params.get("camera_sn") or "").strip() or None

        cameras = await obtenir_cameras(db)
        gestion = await tableau_de_bord_gestion(
            db, date_debut=date_debut, date_fin=date_fin, camera_sn=camera_sn
        )
        contexte.update(
            gestion=gestion,
            cameras=cameras,
            date_debut=date_debut,
            date_fin=date_fin,
            camera_sn_actif=camera_sn,
            est_filtre_actif=(date_debut != aujourdhui or date_fin != aujourdhui or camera_sn is not None),
            libelle_module=libelle_module,
            actions_alerte=ACTIONS_ALERTE,
        )
    return rendre(request, "tableau_de_bord/index.html", contexte)
