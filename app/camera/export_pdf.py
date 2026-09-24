"""Export PDF des données de passage et de comptage."""

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.camera import services
from app.core.exports import generer_pdf, reponse_pdf
from app.core.listes import tout_recuperer


async def exporter_pdf(request: Request, db: AsyncSession) -> Response:
    """Génère un document PDF paysage contenant les passages filtrés."""
    parametres = services.lire_parametres_passages(request)
    passages = await tout_recuperer(db, services.requete_passages(parametres))
    contenu = await run_in_threadpool(
        generer_pdf,
        services.TITRE_EXPORT,
        services.ENTETES_EXPORT,
        services.lignes_export_passages(passages),
        services.filtres_export_passages(parametres),
        largeurs=services.LARGEURS_PDF,
    )
    return reponse_pdf(contenu, services.NOM_FICHIER_EXPORT)
