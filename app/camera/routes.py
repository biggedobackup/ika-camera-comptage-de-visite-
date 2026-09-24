"""Routes du module caméra et comptage de flux.

- api_router : endpoints d'ingestion IoT machine-à-machine (sans CSRF, retour 200 non-vide exigé).
- router : interface de gestion, liste des passages et exports (avec CSRF et authentification).
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.camera import services
from app.camera.export_excel import exporter_excel
from app.camera.export_pdf import exporter_pdf
from app.camera.permissions import GestionnaireCameras, LecteurCameras, peut_gerer_cameras
from app.camera.schemas import CameraCreation, CameraModification
from app.core.dependencies import DbSession
from app.core.listes import paginer
from app.core.security import adresse_ip_client
from app.core.templating import flash, rendre
from app.core.validation import valider

OPTIONS_ROLES_RESEAU = [
    ("master", "Maître (Master — passerelle de flux)"),
    ("slave", "Esclave (Slave — capteur d'extension)"),
    ("client", "Client (Nœud autonome)"),
]

# Router dédié aux endpoints montants (IoT / Webhooks caméras) - Pas de CSRF
api_router = APIRouter(tags=["API Caméra IoT"])

# Router dédié à l'interface d'administration et aux exports
router = APIRouter(tags=["Caméras & Comptage"])

MESSAGE_INTROUVABLE = "La caméra demandée n'existe pas."


# ---------------------------------------------------------------------------
# Endpoints IoT Machine-à-Machine (Protocole V1.0 - Interval Aggregate & Heartbeat)
# ---------------------------------------------------------------------------


@api_router.post("/api/passenger-flow/interval-aggregate", status_code=status.HTTP_200_OK)
async def recevoir_donnees_intervalle(payload: dict[str, Any], request: Request, db: DbSession) -> dict[str, Any]:
    """
    Réceptionne les données agrégées à la minute envoyées par la caméra HX-CCD21 (V1.0).
    Règle constructeur : Réponse obligatoire avec statut 200 et corps non-vide.
    """
    client_ip = adresse_ip_client(request)
    return await services.enregistrer_donnees_intervalle(db, payload, client_ip=client_ip)


@api_router.post("/api/passenger-flow/device-status", status_code=status.HTTP_200_OK)
async def recevoir_heartbeat(payload: dict[str, Any], request: Request, db: DbSession) -> dict[str, Any]:
    """
    Réceptionne le heartbeat d'état du matériel (V1.0).
    """
    client_ip = adresse_ip_client(request)
    return await services.enregistrer_heartbeat(db, payload, client_ip=client_ip)


# ---------------------------------------------------------------------------
# Endpoints IoT de secours (Compatibilité Protocole V2.5)
# ---------------------------------------------------------------------------


@api_router.post("/api/camera/dataUpload", status_code=status.HTTP_200_OK)
async def recevoir_v2_data_upload(payload: dict[str, Any], request: Request, db: DbSession) -> dict[str, Any]:
    """Endpoint de données pour le protocole V2.5."""
    client_ip = adresse_ip_client(request)
    return await services.enregistrer_v2_data_upload(db, payload, client_ip=client_ip)


@api_router.post("/api/camera/heartBeat", status_code=status.HTTP_200_OK)
async def recevoir_v2_heartbeat(payload: dict[str, Any], request: Request, db: DbSession) -> dict[str, Any]:
    """Endpoint de heartbeat pour le protocole V2.5."""
    client_ip = adresse_ip_client(request)
    return await services.enregistrer_v2_heartbeat(db, payload, client_ip=client_ip)


# ---------------------------------------------------------------------------
# WebSocket Temps Réel (Diffusion vers le navigateur)
# ---------------------------------------------------------------------------


@api_router.websocket("/ws/comptage")
async def websocket_flux_comptage(websocket: WebSocket, db: DbSession) -> None:
    """Canal WebSocket temps réel pour recevoir les passages et l'état des appareils."""
    await services.gestionnaire_ws.connecter(websocket)
    try:
        # Envoi de l'état initial des indicateurs dès la connexion
        indicateurs = await services.calculer_indicateurs_comptage(db)
        await websocket.send_json(
            {
                "type": "connexion_initiale",
                "indicateurs": indicateurs.model_dump(),
            }
        )
        while True:
            # Écoute passive pour garder la socket active
            await websocket.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        services.gestionnaire_ws.deconnecter(websocket)


# ---------------------------------------------------------------------------
# Interface Web - Gestion des caméras et passages
# ---------------------------------------------------------------------------


@router.get("/cameras", response_class=HTMLResponse, summary="Liste des caméras")
async def liste_cameras(request: Request, db: DbSession, utilisateur: LecteurCameras) -> HTMLResponse:
    """Affiche la liste des caméras connectées et les indicateurs clés du jour."""
    await services.initialiser_cameras_si_absentes(db)
    cameras = await services.obtenir_cameras(db)
    indicateurs = await services.calculer_indicateurs_comptage(db)

    return rendre(
        request,
        "camera/liste.html",
        {
            "cameras": cameras,
            "indicateurs": indicateurs,
            "peut_gerer": peut_gerer_cameras(utilisateur),
        },
    )


@router.get("/cameras/passages", response_class=HTMLResponse, summary="Historique des passages")
async def liste_passages(request: Request, db: DbSession, utilisateur: LecteurCameras) -> HTMLResponse:
    """Historique paginé et filtré des comptages minute par minute."""
    parametres = services.lire_parametres_passages(request)
    requete = services.requete_passages(parametres)
    passages_pagines = await paginer(db, requete, parametres)
    cameras = await services.obtenir_cameras(db)

    return rendre(
        request,
        "camera/passages.html",
        {
            "passages": passages_pagines,
            "parametres": parametres,
            "cameras": cameras,
            "colonnes_tri": services.COLONNES_TRI_PASSAGES,
            "peut_gerer": peut_gerer_cameras(utilisateur),
        },
    )


@router.get("/cameras/export/excel", summary="Export Excel des passages")
async def export_excel_passages(request: Request, db: DbSession, _: LecteurCameras) -> Response:
    return await exporter_excel(request, db)


@router.get("/cameras/export/pdf", summary="Export PDF des passages")
async def export_pdf_passages(request: Request, db: DbSession, _: LecteurCameras) -> Response:
    return await exporter_pdf(request, db)


@router.get("/cameras/ajouter", response_class=HTMLResponse, summary="Formulaire d'ajout d'une caméra")
async def ajouter_camera_get(
    request: Request,
    _: GestionnaireCameras,
) -> HTMLResponse:
    """Affiche le formulaire d'ajout d'une nouvelle caméra."""
    return rendre(
        request,
        "camera/ajoute.html",
        {
            "modification": False,
            "options_roles": OPTIONS_ROLES_RESEAU,
            "valeurs": {
                "sn": "",
                "nom": "",
                "emplacement": "",
                "ip_address": "",
                "mac_address": "",
                "modele": "HX-CCD21",
                "role_reseau": "master",
                "version_logiciel": "",
            },
            "erreurs": {},
        },
    )


@router.post("/cameras/ajouter", response_class=HTMLResponse, summary="Enregistrer une nouvelle caméra")
async def ajouter_camera_post(
    request: Request,
    db: DbSession,
    _: GestionnaireCameras,
) -> Response:
    """Traite la création manuelle d'une caméra avec validation CSRF."""
    formulaire = await request.form()
    donnees, erreurs = valider(CameraCreation, formulaire)

    if erreurs:
        return rendre(
            request,
            "camera/ajoute.html",
            {
                "modification": False,
                "options_roles": OPTIONS_ROLES_RESEAU,
                "valeurs": dict(formulaire),
                "erreurs": erreurs,
            },
            statut=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    try:
        nouvelle_camera = await services.creer_camera(db, donnees)
    except ValueError as e:
        erreurs["sn"] = str(e)
        return rendre(
            request,
            "camera/ajoute.html",
            {
                "modification": False,
                "options_roles": OPTIONS_ROLES_RESEAU,
                "valeurs": dict(formulaire),
                "erreurs": erreurs,
            },
            statut=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    flash(request, f"La caméra « {nouvelle_camera.libelle_affiche} » ({nouvelle_camera.sn}) a été ajoutée avec succès.")
    return RedirectResponse("/cameras", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/cameras/{camera_id}/supprimer", summary="Supprimer une caméra")
async def supprimer_camera_post(
    camera_id: uuid.UUID,
    request: Request,
    db: DbSession,
    _: GestionnaireCameras,
) -> Response:
    """Supprime définitivement une caméra du système."""
    camera = await services.obtenir_camera_par_id(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=MESSAGE_INTROUVABLE)

    nom_affiche = camera.libelle_affiche
    await services.supprimer_camera(db, camera)
    flash(request, f"La caméra « {nom_affiche} » a été supprimée avec succès.")
    return RedirectResponse("/cameras", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/cameras/{camera_id}", response_class=HTMLResponse, summary="Fiche d'une caméra")
async def fiche_camera(
    camera_id: uuid.UUID, request: Request, db: DbSession, utilisateur: LecteurCameras
) -> HTMLResponse:
    camera = await services.obtenir_camera_par_id(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=MESSAGE_INTROUVABLE)

    return rendre(
        request,
        "camera/detail.html",
        {
            "camera": camera,
            "options_roles": OPTIONS_ROLES_RESEAU,
            "peut_gerer": peut_gerer_cameras(utilisateur),
            "valeurs": {
                "nom": camera.nom or "",
                "emplacement": camera.emplacement or "",
                "ip_address": camera.ip_address or "",
                "mac_address": camera.mac_address or "",
                "modele": camera.modele or "HX-CCD21",
                "role_reseau": camera.role_reseau or "master",
                "version_logiciel": camera.version_logiciel or "",
            },
            "erreurs": {},
        },
    )


@router.post("/cameras/{camera_id}", response_class=HTMLResponse, summary="Modifier une caméra")
async def modifier_camera_post(
    camera_id: uuid.UUID, request: Request, db: DbSession, utilisateur: GestionnaireCameras
) -> Response:
    camera = await services.obtenir_camera_par_id(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=MESSAGE_INTROUVABLE)

    formulaire = await request.form()
    donnees, erreurs = valider(CameraModification, formulaire)

    if erreurs:
        return rendre(
            request,
            "camera/detail.html",
            {
                "camera": camera,
                "options_roles": OPTIONS_ROLES_RESEAU,
                "peut_gerer": True,
                "valeurs": dict(formulaire),
                "erreurs": erreurs,
            },
            statut=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    await services.modifier_camera(db, camera, donnees)
    flash(request, f"La caméra « {camera.libelle_affiche} » a été modifiée avec succès.")
    return RedirectResponse(f"/cameras/{camera_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/cameras/rapport/statistiques", response_class=HTMLResponse, summary="Rapport d'analyse")
async def rapport_statistiques(
    request: Request,
    db: DbSession,
    utilisateur: LecteurCameras,
) -> HTMLResponse:
    """Rapport statistique complet avec filtres par période et par caméra."""
    camera_sn = (request.query_params.get("camera_sn") or "").strip() or None
    date_debut = (request.query_params.get("date_debut") or "").strip() or None
    date_fin = (request.query_params.get("date_fin") or "").strip() or None

    rapport = await services.generer_rapport_comptage(
        db, camera_sn=camera_sn, date_debut=date_debut, date_fin=date_fin
    )
    cameras = await services.obtenir_cameras(db)

    return rendre(
        request,
        "camera/rapport.html",
        {
            "rapport": rapport,
            "cameras": cameras,
            "camera_sn_actif": camera_sn,
            "peut_gerer": peut_gerer_cameras(utilisateur),
        },
    )

