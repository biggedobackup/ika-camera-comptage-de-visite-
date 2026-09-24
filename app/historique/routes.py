"""Routes du module historique : lecture seule (GET uniquement : liste, exports, détail)."""

import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse

from app.core.dependencies import DbSession
from app.core.listes import paginer
from app.core.templating import rendre
from app.historique.export_excel import exporter_excel
from app.historique.export_pdf import exporter_pdf
from app.historique.permissions import LecteurHistorique
from app.historique.services import (
    ACTIONS_ALERTE,
    OPTIONS_ACTIONS,
    comparer_donnees,
    libelle_module,
    lire_parametres,
    obtenir_auteur,
    obtenir_entree,
    options_modules,
    requete_historique,
)

router = APIRouter(tags=["Historique"])


@router.get("/historique", response_class=HTMLResponse, summary="Liste de l'historique")
async def liste(request: Request, db: DbSession, _: LecteurHistorique) -> HTMLResponse:
    parametres, filtres, erreurs_filtres = lire_parametres(request)
    page = await paginer(db, requete_historique(parametres, filtres), parametres)
    return rendre(
        request,
        "historique/liste.html",
        {
            "liste": page,
            "erreurs_filtres": erreurs_filtres,
            "options_actions": OPTIONS_ACTIONS,
            "options_modules": await options_modules(db),
            "libelle_module": libelle_module,
            "actions_alerte": ACTIONS_ALERTE,
        },
    )


@router.get("/historique/export/pdf", summary="Export PDF de l'historique")
async def export_pdf(request: Request, db: DbSession, _: LecteurHistorique) -> Response:
    return await exporter_pdf(request, db)


@router.get("/historique/export/excel", summary="Export Excel de l'historique")
async def export_excel(request: Request, db: DbSession, _: LecteurHistorique) -> Response:
    return await exporter_excel(request, db)


@router.get("/historique/{entree_id}", response_class=HTMLResponse, summary="Détail d'une entrée de l'historique")
async def detail(request: Request, entree_id: uuid.UUID, db: DbSession, _: LecteurHistorique) -> HTMLResponse:
    entree = await obtenir_entree(db, entree_id)
    if entree is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cette entrée de l'historique n'existe pas. Vérifiez le lien ou revenez à la liste.",
        )
    return rendre(
        request,
        "historique/detail.html",
        {
            "entree": entree,
            "auteur": await obtenir_auteur(db, entree),
            "comparaison": comparer_donnees(entree),
            "libelle_module": libelle_module,
            "actions_alerte": ACTIONS_ALERTE,
        },
    )
