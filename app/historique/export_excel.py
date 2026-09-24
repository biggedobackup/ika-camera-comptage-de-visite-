"""Export Excel de l'historique (toutes les lignes correspondant aux filtres et au tri actifs).

La neutralisation des formules (= + - @ tabulation, retour chariot) est faite par app.core.exports.
"""

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exports import generer_excel, reponse_excel
from app.historique.services import ENTETES_EXPORT, NOM_FICHIER_EXPORT, TITRE_EXPORT, donnees_export


async def exporter_excel(request: Request, db: AsyncSession) -> Response:
    lignes, filtres = await donnees_export(request, db)
    contenu = generer_excel(TITRE_EXPORT, ENTETES_EXPORT, lignes, filtres)
    return reponse_excel(contenu, NOM_FICHIER_EXPORT)
