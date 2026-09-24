"""Export PDF de l'historique (toutes les lignes correspondant aux filtres et au tri actifs)."""

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exports import generer_pdf, reponse_pdf
from app.historique.services import (
    ENTETES_EXPORT,
    LARGEURS_EXPORT_PDF,
    NOM_FICHIER_EXPORT,
    TITRE_EXPORT,
    donnees_export,
)


async def exporter_pdf(request: Request, db: AsyncSession) -> Response:
    lignes, filtres = await donnees_export(request, db)
    contenu = generer_pdf(TITRE_EXPORT, ENTETES_EXPORT, lignes, filtres, largeurs=LARGEURS_EXPORT_PDF)
    return reponse_pdf(contenu, NOM_FICHIER_EXPORT)
