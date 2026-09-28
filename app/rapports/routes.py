"""Routes du module Rapports d'analyse de flux passagers (inspiré de Foorir)."""

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.camera.routes import LecteurCameras, peut_gerer_cameras
from app.camera import services as camera_services
from app.core.database import maintenant
from app.core.dependencies import DbSession
from app.core.templating import rendre

router = APIRouter(prefix="/rapports", tags=["Rapports de flux"])

CONFIG_RAPPORTS: dict[str, dict[str, Any]] = {
    "flux": {
        "titre": "Requête de flux (Flow Query)",
        "description": "Visualisation et extraction des flux bruts de franchissement avec filtrage multi-critères.",
        "icone": "bi-search",
        "badge": "Flux bruts",
    },
    "horaire": {
        "titre": "Données horaires (Hourly Data)",
        "description": "Analyse de l'affluence heure par heure (00h à 23h) et détection des pics de fréquentation.",
        "icone": "bi-clock",
        "badge": "Heure par heure",
    },
    "combinaison": {
        "titre": "Analyse combinée (Combination Analysis)",
        "description": "Croisement multidimensionnel entre entrées, sorties physiques et taux de pénétration magasin.",
        "icone": "bi-intersect",
        "badge": "Croisement",
    },
    "clients": {
        "titre": "Requête clients (Customer Query)",
        "description": "Recherche ciblée et segmentation des clients réels qualifiés (visiteurs uniques dédoublés).",
        "icone": "bi-person-badge",
        "badge": "Clients qualifiés",
    },
    "visiteurs": {
        "titre": "Analyse des visiteurs (Visitor Analysis)",
        "description": "Étude globale du volume de visiteurs physiques, clients récurrents et passants de rue.",
        "icone": "bi-people",
        "badge": "Trafic global",
    },
    "employes": {
        "titre": "Personnel & Employés (Employee / Staff)",
        "description": "Comptage et audit des badges du personnel, vigiles et livreurs exclus des flux commerciaux.",
        "icone": "bi-shield-check",
        "badge": "Exclusion staff",
    },
    "entites": {
        "titre": "Analyse des entités (Entity Analysis)",
        "description": "Répartition et comparaison de l'activité par porte, accès et point de vente.",
        "icone": "bi-building",
        "badge": "Portes & Accès",
    },
    "classement": {
        "titre": "Classement des entrées (Entity Ranking)",
        "description": "Palmarès comparatif et performance des accès classés par volume de passage.",
        "icone": "bi-trophy",
        "badge": "Classement",
    },
    "journalier": {
        "titre": "Rapport journalier (Daily Report)",
        "description": "Synthèse consolidée de la journée courante avec indicateurs clés et franchissements.",
        "icone": "bi-calendar-date",
        "badge": "Quotidien",
    },
    "hebdomadaire": {
        "titre": "Rapport hebdomadaire (Weekly Report)",
        "description": "Bilan d'affluence des 7 derniers jours glissants et évolution de la semaine.",
        "icone": "bi-calendar-week",
        "badge": "Hebdo (7 jours)",
    },
    "mensuel": {
        "titre": "Rapport mensuel (Monthly Report)",
        "description": "Consolidation mensuelle du trafic magasin et comparaison des tendances globales.",
        "icone": "bi-calendar-month",
        "badge": "Mensuel",
    },
    "profil": {
        "titre": "Profil des clients (Customer Profile)",
        "description": "Répartition démographique issue de l'IA embarquée : genre, tranches d'âge et durée de séjour.",
        "icone": "bi-person-bounding-box",
        "badge": "Démographie IA",
    },
}


@router.get("", response_class=HTMLResponse, summary="Portail des rapports")
async def index_rapports(request: Request, db: DbSession, utilisateur: LecteurCameras) -> HTMLResponse:
    """Portail central regroupant les 12 modules de rapports analytiques inspirés de Foorir."""
    cameras = await camera_services.obtenir_cameras(db)
    indicateurs = await camera_services.calculer_indicateurs_comptage(db)

    return rendre(
        request,
        "rapports/index.html",
        {
            "rapports_config": CONFIG_RAPPORTS,
            "cameras": cameras,
            "indicateurs": indicateurs,
            "peut_gerer": peut_gerer_cameras(utilisateur),
        },
    )


@router.get("/{type_rapport}", response_class=HTMLResponse, summary="Vue détaillée d'un rapport")
async def detail_rapport(
    type_rapport: str,
    request: Request,
    db: DbSession,
    utilisateur: LecteurCameras,
) -> HTMLResponse:
    """Affiche la vue analytique spécifique d'un rapport avec filtres et graphiques."""
    config = CONFIG_RAPPORTS.get(type_rapport)
    if not config:
        # Si le type n'existe pas, redirection vers l'accueil des rapports
        config = CONFIG_RAPPORTS["journalier"]
        type_rapport = "journalier"

    instant = maintenant()
    aujourdhui = instant.strftime("%Y-%m-%d")

    # Dates par défaut selon le rapport
    date_debut = (request.query_params.get("date_debut") or "").strip()
    date_fin = (request.query_params.get("date_fin") or "").strip()

    if not date_debut:
        if type_rapport == "hebdomadaire":
            date_debut = (instant - timedelta(days=7)).strftime("%Y-%m-%d")
            date_fin = aujourdhui
        elif type_rapport == "mensuel":
            date_debut = instant.strftime("%Y-%m-01")
            date_fin = aujourdhui
        else:
            date_debut = aujourdhui
            date_fin = aujourdhui

    camera_sn = (request.query_params.get("camera_sn") or "").strip() or None

    rapport = await camera_services.generer_rapport_comptage(
        db, camera_sn=camera_sn, date_debut=date_debut, date_fin=date_fin
    )
    cameras = await camera_services.obtenir_cameras(db)

    return rendre(
        request,
        "rapports/detail.html",
        {
            "cle_rapport": type_rapport,
            "config": config,
            "rapports_config": CONFIG_RAPPORTS,
            "rapport": rapport,
            "cameras": cameras,
            "camera_sn_actif": camera_sn,
            "date_debut": date_debut,
            "date_fin": date_fin,
            "peut_gerer": peut_gerer_cameras(utilisateur),
        },
    )
