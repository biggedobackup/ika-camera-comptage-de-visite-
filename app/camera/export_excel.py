"""Export Excel des données de passage et de comptage."""

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.camera import services
from app.core.exports import generer_excel, reponse_excel
from app.core.listes import tout_recuperer


async def exporter_excel(request: Request, db: AsyncSession) -> Response:
    """Génère un classeur Excel contenant tous les passages filtrés."""
    parametres = services.lire_parametres_passages(request)
    passages = await tout_recuperer(db, services.requete_passages(parametres))
    contenu = await run_in_threadpool(
        generer_excel,
        services.TITRE_EXPORT,
        services.ENTETES_EXPORT,
        services.lignes_export_passages(passages),
        services.filtres_export_passages(parametres),
    )
    return reponse_excel(contenu, services.NOM_FICHIER_EXPORT)
