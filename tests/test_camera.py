"""Tests complets du module caméra et comptage de flux (HX-CCD21)."""

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.camera.model import Camera, CameraHeartbeat, PassageComptage
from app.core.database import SessionLocal
from app.utilisateur.model import Role, User


@pytest.fixture
def payload_interval_aggregate_v1() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "type": "interval_aggregate",
        "master_sn": "211000002604280142",
        "device_sns": ["211000002604280142"],
        "timezone": {"name": "Africa/Abidjan", "utc_offset_seconds": 0, "is_dst": False},
        "batch_date": "2026-09-24",
        "stat_basis": "enter",
        "revision": 1741046520,
        "interval_s": 60,
        "start_ts_s": 1741046400,
        "end_ts_s": 1741046460,
        "event_counts": {"enter": 7, "leave": 4, "pass_by": 2, "turn_back": 0},
        "raw_stats": {
            "count": 7,
            "breakdowns": {
                "height_category": [{"height_category": "above_threshold", "count": 7}],
                "age_range|gender": [{"age_range": "17_30", "gender": "male", "count": 7}],
            },
        },
        "final_stats": {
            "count": 4,
            "repeat": 1,
            "breakdowns": {
                "age_range|gender": [
                    {"age_range": "17_30", "gender": "male", "count": 2},
                    {"age_range": "17_30", "gender": "female", "count": 2},
                ]
            },
        },
        "non_customer": {
            "count": 2,
            "breakdowns": {
                "person_type": [{"person_type": "staff", "count": 1}, {"person_type": "rider", "count": 1}]
            },
        },
        "dwell_stats": {
            "count": 3,
            "breakdowns": {"dwell_range": [{"dwell_range": "1_5", "count": 2}]},
        },
    }


@pytest.fixture
def payload_device_status_v1() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "type": "device_status",
        "sn": "211000002604280143",
        "network_role": "master",
        "ts": 1741046520,
        "timezone": {"name": "Africa/Abidjan", "utc_offset_seconds": 0, "is_dst": False},
        "business": {
            "batch_generation": 1741040000,
            "batch_date": "2026-09-24",
            "state": "opening",
        },
        "network": {"slaves": []},
        "faults": [],
    }


# ---------------------------------------------------------------------------
# Tests Endpoints IoT Machine-à-Machine (Sans CSRF)
# ---------------------------------------------------------------------------


async def test_reception_interval_aggregate_v1(
    client: httpx.AsyncClient, payload_interval_aggregate_v1: dict[str, Any]
) -> None:
    """Vérifie la réception du POST V1.0 de la caméra et la persistance."""
    reponse = await client.post(
        "/api/passenger-flow/interval-aggregate",
        json=payload_interval_aggregate_v1,
    )
    assert reponse.status_code == 200
    donnees = reponse.json()
    assert donnees.get("ok") is True

    # Vérification en base de données
    async with SessionLocal() as db:
        camera = (await db.execute(select(Camera).where(Camera.sn == "211000002604280142"))).scalar_one_or_none()
        assert camera is not None
        assert camera.statut_en_ligne is True

        passage = (
            await db.execute(
                select(PassageComptage).where(
                    PassageComptage.master_sn == "211000002604280142",
                    PassageComptage.start_ts_s == 1741046400,
                )
            )
        ).scalar_one_or_none()
        assert passage is not None
        assert passage.entrees == 7
        assert passage.sorties == 4
        assert passage.visiteurs_uniques == 4
        assert passage.visiteurs_recidives == 1
        assert passage.personnel_exclu == 2
        assert passage.revision == 1741046520


async def test_reception_heartbeat_v1(
    client: httpx.AsyncClient, payload_device_status_v1: dict[str, Any]
) -> None:
    """Vérifie la réception du heartbeat de santé V1.0."""
    reponse = await client.post(
        "/api/passenger-flow/device-status",
        json=payload_device_status_v1,
    )
    assert reponse.status_code == 200
    assert reponse.json().get("ok") is True

    async with SessionLocal() as db:
        camera = (await db.execute(select(Camera).where(Camera.sn == "211000002604280143"))).scalar_one_or_none()
        assert camera is not None
        assert camera.statut_en_ligne is True

        hb = (await db.execute(select(CameraHeartbeat).where(CameraHeartbeat.camera_sn == "211000002604280143"))).scalar_one_or_none()
        assert hb is not None
        assert hb.ts == 1741046520
        assert hb.etat == "opening"


async def test_idempotence_et_revision(
    client: httpx.AsyncClient, payload_interval_aggregate_v1: dict[str, Any]
) -> None:
    """
    Règle constructeur :
    - Nouvelle révision plus grande -> écrase les données.
    - Ancienne révision plus petite -> ignorée sans erreur.
    """
    # 1. Premier envoi (revision 100)
    p1 = dict(payload_interval_aggregate_v1)
    p1["revision"] = 100
    p1["event_counts"] = {"enter": 3, "leave": 1, "pass_by": 0, "turn_back": 0}
    p1["final_stats"] = {"count": 3, "repeat": 0}
    rep1 = await client.post("/api/passenger-flow/interval-aggregate", json=p1)
    assert rep1.status_code == 200

    async with SessionLocal() as db:
        res1 = (await db.execute(select(PassageComptage).where(PassageComptage.start_ts_s == 1741046400))).scalar_one()
        assert res1.entrees == 3
        assert res1.revision == 100

    # 2. Deuxième envoi avec révision plus récente (revision 200)
    p2 = dict(payload_interval_aggregate_v1)
    p2["revision"] = 200
    p2["event_counts"] = {"enter": 5, "leave": 2, "pass_by": 0, "turn_back": 0}
    p2["final_stats"] = {"count": 4, "repeat": 1}
    rep2 = await client.post("/api/passenger-flow/interval-aggregate", json=p2)
    assert rep2.status_code == 200

    async with SessionLocal() as db:
        res2 = (await db.execute(select(PassageComptage).where(PassageComptage.start_ts_s == 1741046400))).scalar_one()
        assert res2.entrees == 5
        assert res2.visiteurs_uniques == 4
        assert res2.revision == 200

    # 3. Troisième envoi avec révision ancienne (revision 150 < 200)
    p3 = dict(payload_interval_aggregate_v1)
    p3["revision"] = 150
    p3["event_counts"] = {"enter": 99, "leave": 0, "pass_by": 0, "turn_back": 0}
    rep3 = await client.post("/api/passenger-flow/interval-aggregate", json=p3)
    assert rep3.status_code == 200

    async with SessionLocal() as db:
        res3 = (await db.execute(select(PassageComptage).where(PassageComptage.start_ts_s == 1741046400))).scalar_one()
        # Non modifié car révision 150 < 200
        assert res3.entrees == 5
        assert res3.revision == 200


async def test_compatibilite_protocole_v2(client: httpx.AsyncClient) -> None:
    """Vérifie la compatibilité avec les routes du protocole V2.5."""
    rep_hb = await client.post(
        "/api/camera/heartBeat",
        json={"sn": "211000002604280144", "timestamp": 1741046600},
    )
    assert rep_hb.status_code == 200
    assert rep_hb.json().get("code") == 0

    rep_data = await client.post(
        "/api/camera/dataUpload",
        json={
            "sn": "211000002604280144",
            "time": 1741046600,
            "startTime": 1741046600,
            "endTime": 1741046660,
            "in": 8,
            "out": 3,
            "passby": 1,
            "turnback": 0,
            "avgStayTime": 15000,
        },
    )
    assert rep_data.status_code == 200
    assert rep_data.json().get("code") == 0

    async with SessionLocal() as db:
        passage = (await db.execute(select(PassageComptage).where(PassageComptage.master_sn == "211000002604280144"))).scalar_one_or_none()
        assert passage is not None
        assert passage.entrees == 8
        assert passage.sorties == 3


# ---------------------------------------------------------------------------
# Tests Interface Web & Droits
# ---------------------------------------------------------------------------


async def test_liste_cameras_admin(
    client_admin: httpx.AsyncClient, payload_interval_aggregate_v1: dict[str, Any]
) -> None:
    # Insérer une donnée
    await client_admin.post("/api/passenger-flow/interval-aggregate", json=payload_interval_aggregate_v1)

    page = (await client_admin.get("/cameras")).text
    assert "Caméras 3D de comptage" in page
    assert "211000002604280142" in page
    assert "Main entrance" in page


async def test_modification_camera(
    client_admin: httpx.AsyncClient, payload_interval_aggregate_v1: dict[str, Any]
) -> None:
    await client_admin.post("/api/passenger-flow/interval-aggregate", json=payload_interval_aggregate_v1)

    async with SessionLocal() as db:
        camera = (await db.execute(select(Camera).where(Camera.sn == "211000002604280142"))).scalar_one()
        camera_id = camera.id

    page_detail = (await client_admin.get(f"/cameras/{camera_id}")).text
    assert "État matériel & Réseau" in page_detail
    assert "211000002604280142" in page_detail

    # Modification
    from tests.conftest import extraire_csrf
    csrf = extraire_csrf(page_detail)
    rep_post = await client_admin.post(
        f"/cameras/{camera_id}",
        data={"csrf_token": csrf, "nom": "Entrée Principale VIP", "emplacement": "Hall d'accueil"},
        follow_redirects=True,
    )
    assert rep_post.status_code == 200
    assert "Entrée Principale VIP" in rep_post.text


async def test_passages_liste_et_exports(
    client_admin: httpx.AsyncClient, payload_interval_aggregate_v1: dict[str, Any]
) -> None:
    await client_admin.post("/api/passenger-flow/interval-aggregate", json=payload_interval_aggregate_v1)

    # Page HTML
    rep_html = await client_admin.get("/cameras/passages")
    assert rep_html.status_code == 200
    assert "Flux des camera ( api )" in rep_html.text
    assert "211000002604280142" in rep_html.text

    # Export Excel
    rep_excel = await client_admin.get("/cameras/export/excel")
    assert rep_excel.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in rep_excel.headers["Content-Type"]

    # Export PDF
    rep_pdf = await client_admin.get("/cameras/export/pdf")
    assert rep_pdf.status_code == 200
    assert "application/pdf" in rep_pdf.headers["Content-Type"]


async def test_droits_acces_cameras(
    client: httpx.AsyncClient, client_utilisateur: httpx.AsyncClient, client_manager: httpx.AsyncClient
) -> None:
    # 1. Non authentifié -> redirection login
    rep_anon = await client.get("/cameras")
    assert rep_anon.status_code == 303
    assert "/connexion" in rep_anon.headers["Location"]

    # 2. Utilisateur standard -> 403
    rep_user = await client_utilisateur.get("/cameras")
    assert rep_user.status_code == 403

    # 3. Manager -> lecture OK
    rep_mgr = await client_manager.get("/cameras")
    assert rep_mgr.status_code == 200


async def test_websocket_comptage_diffusion_en_direct(
    client: httpx.AsyncClient, payload_interval_aggregate_v1: dict[str, Any]
) -> None:
    """Vérifie que la réception d'un POST caméra déclenche immédiatement la diffusion WebSocket."""
    from app.camera.websocket import gestionnaire_ws

    class FauxWebSocket:
        def __init__(self) -> None:
            self.messages: list[dict[str, Any]] = []

        async def accept(self) -> None:
            pass

        async def send_json(self, data: dict[str, Any]) -> None:
            self.messages.append(data)

    fake_ws = FauxWebSocket()
    await gestionnaire_ws.connecter(fake_ws)  # type: ignore

    try:
        # Arrivée d'un passage caméra
        rep_cam = await client.post(
            "/api/passenger-flow/interval-aggregate",
            json=payload_interval_aggregate_v1,
        )
        assert rep_cam.status_code == 200

        # Réception de la notification WebSocket en temps réel
        assert len(fake_ws.messages) >= 1
        dernier = fake_ws.messages[-1]
        assert dernier["type"] == "nouveau_passage"
        assert dernier["camera_sn"] == "211000002604280142"
        assert dernier["entrees"] == 7
        assert dernier["visiteurs_uniques"] == 4
    finally:
        gestionnaire_ws.deconnecter(fake_ws)  # type: ignore



async def test_page_rapport_statistiques(
    client_admin: httpx.AsyncClient, payload_interval_aggregate_v1: dict[str, Any]
) -> None:
    """Vérifie l'affichage de la page de rapport statistique."""
    await client_admin.post("/api/passenger-flow/interval-aggregate", json=payload_interval_aggregate_v1)

    from tests.conftest import contenu

    rep = await client_admin.get("/cameras/rapport/statistiques")
    assert rep.status_code == 200
    texte = contenu(rep)
    assert "Rapport d'analyse de flux" in texte
    assert "Affluence par tranche horaire" in texte
    assert "211000002604280142" in texte
    assert "carte-indicateur" in texte


async def test_crud_camera_complet(client_admin: httpx.AsyncClient) -> None:
    """Vérifie le cycle complet de CRUD : Ajout, Consultation, Modification et Suppression."""
    from tests.conftest import extraire_csrf

    # 1. Affichage du formulaire d'ajout
    rep_get = await client_admin.get("/cameras/ajouter")
    assert rep_get.status_code == 200
    assert "Ajouter une caméra" in rep_get.text
    csrf = extraire_csrf(rep_get.text)

    # 2. Ajout d'une nouvelle caméra
    rep_post = await client_admin.post(
        "/cameras/ajouter",
        data={
            "csrf_token": csrf,
            "sn": "SN-TEST-CAMERA-99",
            "nom": "Caméra Test CRUD",
            "emplacement": "Porte Ouest Test",
            "ip_address": "192.168.1.99",
            "modele": "HX-CCD21",
            "role_reseau": "master",
            "version_logiciel": "V1.0-TEST",
        },
        follow_redirects=True,
    )
    assert rep_post.status_code == 200
    assert "SN-TEST-CAMERA-99" in rep_post.text
    assert "Caméra Test CRUD" in rep_post.text

    # Vérification en base
    async with SessionLocal() as db:
        camera = (await db.execute(select(Camera).where(Camera.sn == "SN-TEST-CAMERA-99"))).scalar_one_or_none()
        assert camera is not None
        assert camera.est_en_ligne is False  # Aucun signal émis encore
        camera_id = camera.id

    # 3. Modification
    rep_detail = await client_admin.get(f"/cameras/{camera_id}")
    assert rep_detail.status_code == 200
    csrf_mod = extraire_csrf(rep_detail.text)

    rep_mod = await client_admin.post(
        f"/cameras/{camera_id}",
        data={
            "csrf_token": csrf_mod,
            "nom": "Caméra Test Renommée",
            "emplacement": "Zone 2",
            "ip_address": "192.168.1.199",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "modele": "HX-CCD21-PRO",
            "role_reseau": "slave",
            "version_logiciel": "V2.0",
        },
        follow_redirects=True,
    )
    assert rep_mod.status_code == 200
    assert "Caméra Test Renommée" in rep_mod.text

    # 4. Suppression
    rep_del = await client_admin.post(
        f"/cameras/{camera_id}/supprimer",
        data={"csrf_token": csrf_mod},
        follow_redirects=True,
    )
    assert rep_del.status_code == 200
    assert "a été supprimée avec succès" in rep_del.text

    # Vérification que la caméra n'existe plus
    async with SessionLocal() as db:
        camera_supprimee = (await db.execute(select(Camera).where(Camera.sn == "SN-TEST-CAMERA-99"))).scalar_one_or_none()
        assert camera_supprimee is None


async def test_statut_en_ligne_veridique(client_admin: httpx.AsyncClient) -> None:
    """Vérifie qu'un appareil sans signal est bien affiché hors ligne, et passe en ligne avec un heartbeat."""
    from app.camera.model import Camera
    from app.core.database import maintenant

    async with SessionLocal() as db:
        # Créer une caméra sans contact
        cam = Camera(sn="SN-OFFLINE-TEST", nom="Test Offline", statut_en_ligne=False, dernier_heartbeat=None)
        db.add(cam)
        await db.commit()
        await db.refresh(cam)
        assert cam.est_en_ligne is False

    # Page liste
    page = (await client_admin.get("/cameras")).text
    assert "SN-OFFLINE-TEST" in page
    assert "Hors ligne" in page

    # Émission d'un heartbeat pour cette caméra
    await client_admin.post(
        "/api/passenger-flow/device-status",
        json={
            "schema_version": "1.0",
            "type": "device_status",
            "sn": "SN-OFFLINE-TEST",
            "network_role": "master",
            "ts": int(maintenant().timestamp()),
            "timezone": {},
            "business": {},
            "network": {},
            "faults": [],
        },
    )

    async with SessionLocal() as db:
        cam_maj = (await db.execute(select(Camera).where(Camera.sn == "SN-OFFLINE-TEST"))).scalar_one()
        assert cam_maj.est_en_ligne is True

    # Simulation d'un arrêt de signal : le heartbeat date de 10 minutes (ou 2 jours)
    from datetime import timedelta
    async with SessionLocal() as db:
        cam_stale = (await db.execute(select(Camera).where(Camera.sn == "SN-OFFLINE-TEST"))).scalar_one()
        cam_stale.dernier_heartbeat = maintenant() - timedelta(minutes=10)
        cam_stale.statut_en_ligne = True  # Même si statut_en_ligne est True en base
        await db.commit()
        await db.refresh(cam_stale)
        assert cam_stale.est_en_ligne is False

    # Sur la page /cameras, la caméra doit impérativement apparaître Hors ligne
    page_apres = (await client_admin.get("/cameras")).text
    assert "SN-OFFLINE-TEST" in page_apres
    # Vérifier que le statut affiché est Hors ligne
    assert "Hors ligne" in page_apres

    # Nettoyage
    async with SessionLocal() as db:
        cam_del = (await db.execute(select(Camera).where(Camera.sn == "SN-OFFLINE-TEST"))).scalar_one()
        await db.delete(cam_del)
        await db.commit()


async def test_ajout_et_modification_tous_les_champs(client_admin: httpx.AsyncClient) -> None:
    """Vérifie que l'on peut ajouter et modifier absolument tous les champs de la caméra (SN inclus)."""
    from tests.conftest import extraire_csrf

    # 1. Ajout complet avec tous les champs
    page_ajout = (await client_admin.get("/cameras/ajouter")).text
    csrf1 = extraire_csrf(page_ajout)
    rep_ajout = await client_admin.post(
        "/cameras/ajouter",
        data={
            "csrf_token": csrf1,
            "sn": "SN-FULL-CONFIG-001",
            "modele": "HX-CCD21-PRO",
            "nom": "Entrée Principale Nord",
            "emplacement": "Bâtiment A, RDC",
            "ip_address": "192.168.1.180",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "role_reseau": "master",
            "version_logiciel": "V2.1.0",
            "statut_en_ligne": "true",
            "hauteur_installation": "310",
            "hauteur_filtrage": "115",
            "mode_enfant": "true",
            "sens_comptage": "inverse",
            "intervalle_envoi": "60",
            "notes": "Caméra calibrée avec détection IA enfants activée.",
        },
        follow_redirects=True,
    )
    assert rep_ajout.status_code == 200

    async with SessionLocal() as db:
        cam = (await db.execute(select(Camera).where(Camera.sn == "SN-FULL-CONFIG-001"))).scalar_one_or_none()
        assert cam is not None
        assert cam.nom == "Entrée Principale Nord"
        assert cam.modele == "HX-CCD21-PRO"
        assert cam.ip_address == "192.168.1.180"
        assert cam.mac_address == "AA:BB:CC:DD:EE:FF"
        assert cam.role_reseau == "master"
        assert cam.version_logiciel == "V2.1.0"
        assert cam.statut_en_ligne is True
        assert cam.hauteur_installation == 310
        assert cam.hauteur_filtrage == 115
        assert cam.mode_enfant is True
        assert cam.sens_comptage == "inverse"
        assert cam.intervalle_envoi == 60
        assert "calibrée" in (cam.notes or "")
        cam_id = cam.id

    # 2. Modification de l'intégralité des champs (y compris le SN !)
    page_detail = (await client_admin.get(f"/cameras/{cam_id}")).text
    assert "Modifier tous les paramètres de la caméra" in page_detail
    assert "SN-FULL-CONFIG-001" in page_detail
    assert "310 cm" in page_detail
    csrf2 = extraire_csrf(page_detail)

    rep_modif = await client_admin.post(
        f"/cameras/{cam_id}",
        data={
            "csrf_token": csrf2,
            "sn": "SN-FULL-CONFIG-002",  # Modification du numéro de série
            "modele": "HX-CCD21-V2",
            "nom": "Entrée VIP Rénovée",
            "emplacement": "Bâtiment B, Étage 1",
            "ip_address": "192.168.1.199",
            "mac_address": "11:22:33:44:55:66",
            "role_reseau": "slave",
            "version_logiciel": "V2.5.0",
            "statut_en_ligne": "false",
            "hauteur_installation": "290",
            "hauteur_filtrage": "100",
            "mode_enfant": "false",
            "sens_comptage": "normal",
            "intervalle_envoi": "120",
            "notes": "Mise à jour suite au changement de porte.",
        },
        follow_redirects=True,
    )
    assert rep_modif.status_code == 200

    async with SessionLocal() as db:
        # L'ancien SN ne doit plus exister
        ancien = (await db.execute(select(Camera).where(Camera.sn == "SN-FULL-CONFIG-001"))).scalar_one_or_none()
        assert ancien is None

        # Le nouveau SN doit exister avec tous les champs mis à jour
        maj = (await db.execute(select(Camera).where(Camera.sn == "SN-FULL-CONFIG-002"))).scalar_one()
        assert maj.id == cam_id
        assert maj.nom == "Entrée VIP Rénovée"
        assert maj.emplacement == "Bâtiment B, Étage 1"
        assert maj.ip_address == "192.168.1.199"
        assert maj.mac_address == "11:22:33:44:55:66"
        assert maj.modele == "HX-CCD21-V2"
        assert maj.role_reseau == "slave"
        assert maj.version_logiciel == "V2.5.0"
        assert maj.hauteur_installation == 290
        assert maj.hauteur_filtrage == 100
        assert maj.mode_enfant is False
        assert maj.sens_comptage == "normal"
        assert maj.intervalle_envoi == 120
        assert "changement de porte" in (maj.notes or "")

        # Nettoyage
        await db.delete(maj)
        await db.commit()


async def test_rapport_donnees_json_et_websocket_refresh(
    client_admin: httpx.AsyncClient, payload_interval_aggregate_v1: dict[str, Any]
) -> None:
    """Vérifie l'endpoint JSON du rapport et l'affichage temps réel."""
    await client_admin.post("/api/passenger-flow/interval-aggregate", json=payload_interval_aggregate_v1)

    # 1. Vérification de la page HTML avec indicateur WebSocket et conteneur de données
    rep_html = await client_admin.get("/cameras/rapport/statistiques")
    assert rep_html.status_code == 200
    assert "data-page-rapport" in rep_html.text
    assert "badge-temps-reel" in rep_html.text
    assert "data-rapport-entrees" in rep_html.text

    # 2. Vérification de l'API JSON temps réel
    rep_json = await client_admin.get("/cameras/rapport/donnees?date_debut=2026-09-24&date_fin=2026-09-24")
    assert rep_json.status_code == 200
    donnees = rep_json.json()
    assert "entrees" in donnees
    assert "visiteurs_uniques" in donnees
    assert "repartition_cameras" in donnees
    assert "repartition_heures" in donnees



