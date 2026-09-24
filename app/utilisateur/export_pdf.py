"""Export PDF de la liste des utilisateurs (toutes les lignes correspondant aux filtres et au tri actifs)."""

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.exports import generer_pdf, reponse_pdf
from app.core.listes import tout_recuperer
from app.utilisateur import services


async def exporter_pdf(request: Request, db: AsyncSession) -> Response:
    parametres = services.lire_parametres(request)
    comptes = await tout_recuperer(db, services.requete_utilisateurs(parametres))
    contenu = await run_in_threadpool(
        generer_pdf,
        services.TITRE_EXPORT,
        services.ENTETES_EXPORT,
        services.lignes_export(comptes),
        services.filtres_export(parametres),
        largeurs=services.LARGEURS_PDF,
    )
    return reponse_pdf(contenu, services.NOM_FICHIER_EXPORT)
