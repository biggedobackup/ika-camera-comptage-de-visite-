"""Export Excel de la liste des utilisateurs (toutes les lignes correspondant aux filtres et au tri actifs).

La neutralisation de l'injection de formules est assurée par app.core.exports.generer_excel.
"""

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.exports import generer_excel, reponse_excel
from app.core.listes import tout_recuperer
from app.utilisateur import services


async def exporter_excel(request: Request, db: AsyncSession) -> Response:
    parametres = services.lire_parametres(request)
    comptes = await tout_recuperer(db, services.requete_utilisateurs(parametres))
    contenu = await run_in_threadpool(
        generer_excel,
        services.TITRE_EXPORT,
        services.ENTETES_EXPORT,
        services.lignes_export(comptes),
        services.filtres_export(parametres),
    )
    return reponse_excel(contenu, services.NOM_FICHIER_EXPORT)
