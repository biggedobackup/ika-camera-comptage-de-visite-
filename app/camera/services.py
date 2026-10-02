"""Services du module caméra : ingestion des flux IoT, gestion des révisions, idempotentce,
requêtes de liste, indicateurs statistiques et exports (PDF / Excel)."""

import dataclasses
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import BigInteger, ColumnElement, Select, and_, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.camera.model import Camera, CameraHeartbeat, PassageComptage
from app.camera.schemas import (
    CameraCreation,
    CameraModification,
    DeviceStatusPayload,
    IndicateursComptage,
    IntervalAggregatePayload,
)
from app.camera.websocket import gestionnaire_ws
from app.core.database import maintenant
from app.core.listes import (
    ParametresListe,
    appliquer_recherche,
    appliquer_tri,
    decrire_filtres,
    lire_parametres_liste,
)

logger = logging.getLogger("app.camera")

MODULE = "camera"

# Noms et configurations des 4 caméras par défaut
CAMERAS_PAR_DEFAUT = {
    "211000002604280142": {"nom": "Main entrance", "emplacement": "Main entrance"},
    "211000002604280143": {"nom": "second door", "emplacement": "second gate"},
    "211000002604280144": {"nom": "4th gate", "emplacement": "4th gate"},
    "211000002604280146": {"nom": "3rd entry", "emplacement": "3rd entry"},
}

# Configuration des exports
TITRE_EXPORT = "Historique des passages et comptage de flux"
NOM_FICHIER_EXPORT = "comptage_flux_visiteurs"
ENTETES_EXPORT = (
    "Date & Heure",
    "Caméra (SN)",
    "Nom entrée",
    "Entrées",
    "Sorties",
    "Visiteurs uniques",
    "Récidives",
    "Personnel exclu",
    "Passants",
)
LARGEURS_PDF = (35, 45, 40, 22, 22, 30, 22, 28, 22)


# ---------------------------------------------------------------------------
# Initialisation et gestion des caméras
# ---------------------------------------------------------------------------


async def obtenir_ou_creer_camera(
    db: AsyncSession, sn: str, ip_address: str | None = None, role_reseau: str = "master"
) -> Camera:
    """Récupère une caméra par son numéro de série ou la crée automatiquement."""
    requete = select(Camera).where(Camera.sn == sn)
    resultat = await db.execute(requete)
    camera = resultat.scalar_one_or_none()

    meta_defaut = CAMERAS_PAR_DEFAUT.get(sn, {})

    if camera is None:
        camera = Camera(
            sn=sn,
            nom=meta_defaut.get("nom", f"Caméra {sn}"),
            emplacement=meta_defaut.get("emplacement", f"Entrée {sn}"),
            ip_address=ip_address,
            role_reseau=role_reseau,
            statut_en_ligne=True,
            dernier_heartbeat=maintenant(),
        )
        db.add(camera)
        await db.flush()
    else:
        camera.statut_en_ligne = True
        camera.dernier_heartbeat = maintenant()
        if ip_address and ip_address != camera.ip_address:
            camera.ip_address = ip_address
        if role_reseau:
            camera.role_reseau = role_reseau
        await db.flush()

    return camera


# Délai en secondes au-delà duquel un appareil sans signal est considéré hors ligne (3 min)
DELAI_EN_LIGNE_SECONDES = 180


async def initialiser_cameras_si_absentes(db: AsyncSession) -> None:
    """Pré-enregistre les 4 caméras par défaut uniquement si la base est totalement vierge."""
    nb_existantes = (await db.execute(select(func.count(Camera.id)))).scalar_one()
    if nb_existantes > 0:
        return

    for sn, meta in CAMERAS_PAR_DEFAUT.items():
        nouvelle = Camera(
            sn=sn,
            nom=meta["nom"],
            emplacement=meta["emplacement"],
            statut_en_ligne=False,
            dernier_heartbeat=None,
        )
        db.add(nouvelle)
    await db.commit()


# ---------------------------------------------------------------------------
# Ingestion des flux IoT (Protocole V1.0 - Interval Aggregate & Heartbeat)
# ---------------------------------------------------------------------------


async def enregistrer_donnees_intervalle(
    db: AsyncSession, payload_data: dict[str, Any] | IntervalAggregatePayload, client_ip: str | None = None
) -> dict[str, Any]:
    """
    Ingère un message interval-aggregate (Uplink V1.0) émis par la caméra.
    Règles imposées par la documentation HX-CCD21 :
    1. Clé primaire d'idempotence : (master_sn, batch_date, start_ts_s).
    2. Si le segment existe déjà et revision > revision_existante : écraser tout le record.
    3. Si revision <= revision_existante : ignorer, mais renvoyer 200 non-vide.
    4. Réponse obligatoire non-vide pour acquitter auprès de la caméra.
    """
    if isinstance(payload_data, IntervalAggregatePayload):
        data = payload_data.model_dump()
    else:
        data = payload_data

    master_sn = data["master_sn"]
    batch_date = data["batch_date"]
    start_ts_s = int(data["start_ts_s"])
    end_ts_s = int(data.get("end_ts_s", start_ts_s + data.get("interval_s", 60)))
    revision = int(data["revision"])
    stat_basis = data.get("stat_basis", "enter")
    interval_s = int(data.get("interval_s", 60))

    camera = await obtenir_ou_creer_camera(db, master_sn, ip_address=client_ip, role_reseau="master")

    # Recherche si ce créneau (minute) a déjà été reçu
    requete = select(PassageComptage).where(
        PassageComptage.master_sn == master_sn,
        PassageComptage.batch_date == batch_date,
        PassageComptage.start_ts_s == start_ts_s,
    )
    existant = (await db.execute(requete)).scalar_one_or_none()

    # Extraction des flux
    event_counts = data.get("event_counts", {})
    entrees = int(event_counts.get("enter", 0))
    sorties = int(event_counts.get("leave", 0))
    passants = int(event_counts.get("pass_by", 0))
    demi_tours = int(event_counts.get("turn_back", 0))

    final_stats = data.get("final_stats", {})
    visiteurs_uniques = int(final_stats.get("count", 0))
    visiteurs_recidives = int(final_stats.get("repeat", 0))

    non_customer = data.get("non_customer", {})
    personnel_exclu = int(non_customer.get("count", 0))

    dwell_stats = data.get("dwell_stats", {})
    duree_sejour = int(dwell_stats.get("count", 0))

    final_breakdowns = final_stats.get("breakdowns") or {}
    age_genre = final_breakdowns.get("age_range|gender")
    taille = final_breakdowns.get("height_category")
    sejour = (dwell_stats.get("breakdowns") or {}).get("dwell_range")

    horodatage_debut = datetime.fromtimestamp(start_ts_s, UTC)

    if existant is None:
        passage = PassageComptage(
            camera_id=camera.id,
            master_sn=master_sn,
            batch_date=batch_date,
            stat_basis=stat_basis,
            revision=revision,
            interval_s=interval_s,
            start_ts_s=start_ts_s,
            end_ts_s=end_ts_s,
            horodatage_debut=horodatage_debut,
            entrees=entrees,
            sorties=sorties,
            passants=passants,
            demi_tours=demi_tours,
            visiteurs_uniques=visiteurs_uniques,
            visiteurs_recidives=visiteurs_recidives,
            personnel_exclu=personnel_exclu,
            duree_sejour_moyenne_sec=duree_sejour,
            repartition_age_genre=age_genre,
            repartition_taille=taille,
            repartition_sejour=sejour,
            donnees_brutes=data,
        )
        db.add(passage)
        logger.info(
            "Nouveau passage enregistré pour %s [%s] : %d entrées (%d uniques)",
            master_sn,
            horodatage_debut.strftime("%H:%M:%S"),
            entrees,
            visiteurs_uniques,
        )
    elif revision > existant.revision:
        # Écrasement complet de la minute par la révision plus récente
        existant.camera_id = camera.id
        existant.revision = revision
        existant.stat_basis = stat_basis
        existant.interval_s = interval_s
        existant.end_ts_s = end_ts_s
        existant.entrees = entrees
        existant.sorties = sorties
        existant.passants = passants
        existant.demi_tours = demi_tours
        existant.visiteurs_uniques = visiteurs_uniques
        existant.visiteurs_recidives = visiteurs_recidives
        existant.personnel_exclu = personnel_exclu
        existant.duree_sejour_moyenne_sec = duree_sejour
        existant.repartition_age_genre = age_genre
        existant.repartition_taille = taille
        existant.repartition_sejour = sejour
        existant.donnees_brutes = data
        logger.info("Mise à jour (révision %d) pour %s à %s", revision, master_sn, horodatage_debut)
    else:
        logger.debug("Révision ignorée (%d <= %d) pour %s", revision, existant.revision, master_sn)

    await db.commit()

    # Diffusion temps réel via WebSocket aux clients connectés
    try:
        indicateurs = await calculer_indicateurs_comptage(db)
        await gestionnaire_ws.diffuser(
            {
                "type": "nouveau_passage",
                "camera_sn": master_sn,
                "camera_nom": camera.libelle_affiche,
                "horodatage": horodatage_debut.strftime("%d/%m/%Y %H:%M"),
                "heure": horodatage_debut.strftime("%H:%M"),
                "entrees": entrees,
                "sorties": sorties,
                "visiteurs_uniques": visiteurs_uniques,
                "visiteurs_recidives": visiteurs_recidives,
                "personnel_exclu": personnel_exclu,
                "passants": passants,
                "indicateurs": indicateurs.model_dump(),
            }
        )
    except Exception:
        logger.exception("Erreur lors de la diffusion WebSocket nouveau_passage")

    return {"ok": True, "code": 0, "msg": "success"}


async def enregistrer_heartbeat(
    db: AsyncSession, payload_data: dict[str, Any] | DeviceStatusPayload, client_ip: str | None = None
) -> dict[str, Any]:
    """Ingère un heartbeat (Uplink V1.0) de statut caméra."""
    if isinstance(payload_data, DeviceStatusPayload):
        data = payload_data.model_dump()
    else:
        data = payload_data

    sn = data["sn"]
    ts = int(data.get("ts", int(maintenant().timestamp())))
    role = data.get("network_role", "master")

    business = data.get("business", {})
    etat = business.get("state") if isinstance(business, dict) else None

    camera = await obtenir_ou_creer_camera(db, sn, ip_address=client_ip, role_reseau=role)

    heartbeat = CameraHeartbeat(
        camera_id=camera.id,
        camera_sn=sn,
        ts=ts,
        etat=etat,
        ip_address=client_ip or camera.ip_address,
        donnees=data,
    )
    db.add(heartbeat)
    await db.commit()

    try:
        indicateurs = await calculer_indicateurs_comptage(db)
        await gestionnaire_ws.diffuser(
            {
                "type": "heartbeat",
                "camera_sn": sn,
                "camera_nom": camera.libelle_affiche,
                "statut_en_ligne": True,
                "dernier_heartbeat": camera.dernier_heartbeat.strftime("%d/%m/%Y %H:%M")
                if camera.dernier_heartbeat
                else "",
                "indicateurs": indicateurs.model_dump(),
            }
        )
    except Exception:
        logger.exception("Erreur lors de la diffusion WebSocket heartbeat")

    return {"ok": True, "status": "alive"}


# ---------------------------------------------------------------------------
# Ingestion des flux IoT (Protocole V2.5 de secours)
# ---------------------------------------------------------------------------


async def enregistrer_v2_data_upload(
    db: AsyncSession, data: dict[str, Any], client_ip: str | None = None
) -> dict[str, Any]:
    """Ingère les données du protocole V2.5 (POST /api/camera/dataUpload)."""
    sn = data.get("sn", "INCONNU")
    time_val = int(data.get("time", int(maintenant().timestamp())))
    start_time = int(data.get("startTime", time_val))
    end_time = int(data.get("endTime", start_time + 60))

    camera = await obtenir_ou_creer_camera(db, sn, ip_address=client_ip)

    # Agrégation à la minute exacte
    minute_ts = (start_time // 60) * 60
    horodatage = datetime.fromtimestamp(minute_ts, UTC)
    batch_date = horodatage.strftime("%Y-%m-%d")

    entrees = int(data.get("in", 0))
    sorties = int(data.get("out", 0))
    passby = int(data.get("passby", 0))
    turnback = int(data.get("turnback", 0))
    avg_stay = int(data.get("avgStayTime", 0))

    # Recherche si un enregistrement existe déjà pour cette caméra et cette minute
    requete = select(PassageComptage).where(
        PassageComptage.master_sn == sn,
        PassageComptage.batch_date == batch_date,
        PassageComptage.start_ts_s == minute_ts,
    )
    existant = (await db.execute(requete)).scalar_one_or_none()

    if existant is None:
        # On insère une nouvelle ligne si au moins une activité est détectée
        if entrees > 0 or sorties > 0 or passby > 0 or turnback > 0:
            passage = PassageComptage(
                camera_id=camera.id,
                master_sn=sn,
                batch_date=batch_date,
                stat_basis="enter",
                revision=time_val,
                interval_s=60,
                start_ts_s=minute_ts,
                end_ts_s=minute_ts + 60,
                horodatage_debut=horodatage,
                entrees=entrees,
                sorties=sorties,
                passants=passby,
                demi_tours=turnback,
                visiteurs_uniques=entrees,
                visiteurs_recidives=0,
                personnel_exclu=0,
                duree_sejour_moyenne_sec=avg_stay // 1000 if avg_stay > 1000 else avg_stay,
                donnees_brutes=data,
            )
            db.add(passage)
    else:
        # Cumul incrémental sur le créneau de la minute courante
        existant.entrees += entrees
        existant.sorties += sorties
        existant.passants += passby
        existant.demi_tours += turnback
        existant.visiteurs_uniques += entrees
        existant.revision = max(existant.revision, time_val)
        if avg_stay > 0:
            stay_sec = avg_stay // 1000 if avg_stay > 1000 else avg_stay
            existant.duree_sejour_moyenne_sec = (
                (existant.duree_sejour_moyenne_sec + stay_sec) // 2
                if existant.duree_sejour_moyenne_sec > 0
                else stay_sec
            )
        existant.donnees_brutes = data

    await db.commit()

    try:
        indicateurs = await calculer_indicateurs_comptage(db)
        await gestionnaire_ws.diffuser(
            {
                "type": "nouveau_passage",
                "camera_sn": sn,
                "camera_nom": camera.libelle_affiche,
                "horodatage": horodatage.strftime("%d/%m/%Y %H:%M"),
                "heure": horodatage.strftime("%H:%M"),
                "entrees": entrees,
                "sorties": sorties,
                "visiteurs_uniques": entrees,
                "visiteurs_recidives": 0,
                "personnel_exclu": 0,
                "passants": passby,
                "indicateurs": indicateurs.model_dump(),
            }
        )
    except Exception:
        logger.exception("Erreur lors de la diffusion WebSocket v2_data_upload")

    return {"code": 0, "msg": "Reportsubmittedsuccessfully", "data": {"sn": sn, "time": time_val}}


async def enregistrer_v2_heartbeat(
    db: AsyncSession, data: dict[str, Any], client_ip: str | None = None
) -> dict[str, Any]:
    """Ingère le heartbeat du protocole V2.5 (POST /api/camera/heartBeat)."""
    sn = data.get("sn", "INCONNU")
    ts = int(data.get("timestamp", int(maintenant().timestamp())))

    camera = await obtenir_ou_creer_camera(db, sn, ip_address=client_ip)

    heartbeat = CameraHeartbeat(
        camera_id=camera.id,
        camera_sn=sn,
        ts=ts,
        ip_address=client_ip,
        donnees=data,
    )
    db.add(heartbeat)
    await db.commit()

    return {
        "msg": "success",
        "code": 0,
        "data": {
            "uploadInterval": 0,
            "dataMode": "Add",
            "timezone": 0,
            "sn": sn,
            "time": ts,
        },
    }


# ---------------------------------------------------------------------------
# Consultation, Statistiques et UI
# ---------------------------------------------------------------------------


COLONNES_TRI_PASSAGES = {
    "horodatage": PassageComptage.horodatage_debut,
    "entrees": PassageComptage.entrees,
    "sorties": PassageComptage.sorties,
    "uniques": PassageComptage.visiteurs_uniques,
}


def lire_parametres_passages(request: Request) -> ParametresListe:
    """Lit les filtres spécifiques aux passages."""
    return lire_parametres_liste(
        request,
        colonnes_tri=COLONNES_TRI_PASSAGES.keys(),
        tri_defaut="horodatage",
        ordre_defaut="desc",
        filtres=("camera_sn", "date_jour"),
    )


def requete_passages(parametres: ParametresListe) -> Select[tuple[PassageComptage]]:
    """Construit la requête de sélection filtrée et triée."""
    from sqlalchemy.orm import selectinload

    requete = select(PassageComptage).options(selectinload(PassageComptage.camera))
    clauses: list[ColumnElement[bool]] = []

    camera_sn = parametres.filtres.get("camera_sn")
    if camera_sn:
        clauses.append(PassageComptage.master_sn == camera_sn)

    date_str = parametres.filtres.get("date_jour")
    if date_str:
        clauses.append(PassageComptage.batch_date == date_str)

    if parametres.recherche:
        motif = f"%{parametres.recherche}%"
        clauses.append(
            or_(
                PassageComptage.master_sn.ilike(motif),
                PassageComptage.batch_date.ilike(motif),
            )
        )

    if clauses:
        requete = requete.where(and_(*clauses))

    colonne = COLONNES_TRI_PASSAGES.get(parametres.tri, PassageComptage.horodatage_debut)
    requete = requete.order_by(desc(colonne) if parametres.ordre == "desc" else colonne)
    return requete


async def obtenir_cameras(db: AsyncSession) -> Sequence[Camera]:
    """Retourne toutes les caméras enregistrées en synchronisant leur état en ligne."""
    seuil = maintenant() - timedelta(seconds=DELAI_EN_LIGNE_SECONDES)
    await db.execute(
        update(Camera)
        .where(or_(Camera.dernier_heartbeat.is_(None), Camera.dernier_heartbeat < seuil))
        .values(statut_en_ligne=False)
    )
    await db.execute(
        update(Camera)
        .where(Camera.dernier_heartbeat >= seuil)
        .values(statut_en_ligne=True)
    )
    await db.flush()

    resultat = await db.execute(select(Camera).order_by(Camera.sn.asc()))
    return resultat.scalars().all()


async def obtenir_camera_par_id(db: AsyncSession, camera_id: uuid.UUID) -> Camera | None:
    return await db.get(Camera, camera_id)


async def creer_camera(db: AsyncSession, donnees: CameraCreation) -> Camera:
    """Crée manuellement une nouvelle caméra de comptage avec tous les champs configurables."""
    sn_propre = donnees.sn.strip()
    requete_sn = select(Camera).where(Camera.sn == sn_propre)
    deja_present = (await db.execute(requete_sn)).scalar_one_or_none()
    if deja_present:
        raise ValueError(f"Une caméra avec le numéro de série « {sn_propre} » existe déjà.")

    config = {
        "hauteur_installation": donnees.hauteur_installation,
        "hauteur_filtrage": donnees.hauteur_filtrage,
        "mode_enfant": donnees.mode_enfant,
        "sens_comptage": donnees.sens_comptage,
        "intervalle_envoi": donnees.intervalle_envoi,
        "notes": donnees.notes.strip() if donnees.notes else None,
    }

    camera = Camera(
        sn=sn_propre,
        nom=donnees.nom.strip() if donnees.nom else None,
        emplacement=donnees.emplacement.strip() if donnees.emplacement else None,
        ip_address=donnees.ip_address.strip() if donnees.ip_address else None,
        mac_address=donnees.mac_address.strip() if donnees.mac_address else None,
        modele=donnees.modele.strip() if donnees.modele else "HX-CCD21",
        role_reseau=donnees.role_reseau.strip() if donnees.role_reseau else "master",
        version_logiciel=donnees.version_logiciel.strip() if donnees.version_logiciel else None,
        statut_en_ligne=donnees.statut_en_ligne,
        dernier_heartbeat=maintenant() if donnees.statut_en_ligne else None,
        configuration=config,
    )
    db.add(camera)
    await db.commit()
    await db.refresh(camera)
    return camera


async def modifier_camera(db: AsyncSession, camera: Camera, donnees: CameraModification) -> Camera:
    """Met à jour l'ensemble de tous les champs configurables de la caméra."""
    # 1. Numéro de série (SN) avec validation d'unicité et préservation de l'historique
    if donnees.sn is not None and donnees.sn.strip():
        nouveau_sn = donnees.sn.strip()
        if nouveau_sn != camera.sn:
            deja_pris = (
                await db.execute(select(Camera).where(Camera.sn == nouveau_sn, Camera.id != camera.id))
            ).scalar_one_or_none()
            if deja_pris:
                raise ValueError(f"Une caméra avec le numéro de série « {nouveau_sn} » existe déjà.")

            ancien_sn = camera.sn
            camera.sn = nouveau_sn

            # Met à jour les liaisons par code SN dans les comptages et pings
            await db.execute(
                update(PassageComptage)
                .where((PassageComptage.camera_id == camera.id) | (PassageComptage.master_sn == ancien_sn))
                .values(master_sn=nouveau_sn)
            )
            await db.execute(
                update(CameraHeartbeat)
                .where((CameraHeartbeat.camera_id == camera.id) | (CameraHeartbeat.camera_sn == ancien_sn))
                .values(camera_sn=nouveau_sn)
            )

    # 2. Identification & Emplacement
    if donnees.nom is not None:
        camera.nom = donnees.nom.strip() or None
    if donnees.emplacement is not None:
        camera.emplacement = donnees.emplacement.strip() or None

    # 3. Paramètres réseau & Matériel
    if donnees.ip_address is not None:
        camera.ip_address = donnees.ip_address.strip() or None
    if donnees.mac_address is not None:
        camera.mac_address = donnees.mac_address.strip() or None
    if donnees.modele is not None and donnees.modele.strip():
        camera.modele = donnees.modele.strip()
    if donnees.role_reseau is not None and donnees.role_reseau.strip():
        camera.role_reseau = donnees.role_reseau.strip()
    if donnees.version_logiciel is not None:
        camera.version_logiciel = donnees.version_logiciel.strip() or None

    # 4. Statut réseau / En ligne
    if donnees.statut_en_ligne is not None:
        camera.statut_en_ligne = donnees.statut_en_ligne
        if donnees.statut_en_ligne and not camera.dernier_heartbeat:
            camera.dernier_heartbeat = maintenant()

    # 5. Configuration technique HX-CCD21 (JSONB)
    config = dict(camera.configuration or {})
    if donnees.hauteur_installation is not None:
        config["hauteur_installation"] = donnees.hauteur_installation
    elif "hauteur_installation" in config and donnees.hauteur_installation is None:
        config["hauteur_installation"] = None

    if donnees.hauteur_filtrage is not None:
        config["hauteur_filtrage"] = donnees.hauteur_filtrage
    elif "hauteur_filtrage" in config and donnees.hauteur_filtrage is None:
        config["hauteur_filtrage"] = None

    if donnees.mode_enfant is not None:
        config["mode_enfant"] = donnees.mode_enfant

    if donnees.sens_comptage is not None:
        config["sens_comptage"] = donnees.sens_comptage

    if donnees.intervalle_envoi is not None:
        config["intervalle_envoi"] = donnees.intervalle_envoi

    if donnees.notes is not None:
        config["notes"] = donnees.notes.strip() or None

    camera.configuration = config

    await db.commit()
    await db.refresh(camera)
    return camera


async def supprimer_camera(db: AsyncSession, camera: Camera) -> None:
    """Supprime définitivement une caméra et ses données associées."""
    await db.delete(camera)
    await db.commit()


async def calculer_indicateurs_comptage(db: AsyncSession) -> IndicateursComptage:
    """Calcule les indicateurs du jour pour le tableau de bord avec statut temps réel véridique."""
    aujourdhui = maintenant().strftime("%Y-%m-%d")

    totaux = (
        await db.execute(
            select(
                func.coalesce(func.sum(PassageComptage.entrees), 0),
                func.coalesce(func.sum(PassageComptage.sorties), 0),
                func.coalesce(func.sum(PassageComptage.visiteurs_uniques), 0),
                func.coalesce(func.sum(PassageComptage.visiteurs_recidives), 0),
                func.coalesce(func.sum(PassageComptage.personnel_exclu), 0),
            ).where(PassageComptage.batch_date == aujourdhui)
        )
    ).one()

    # Seuil temps réel strict : signal reçu il y a moins de DELAI_EN_LIGNE_SECONDES (180s)
    seuil_en_ligne = maintenant() - timedelta(seconds=DELAI_EN_LIGNE_SECONDES)

    nb_total_cam, nb_en_ligne = (
        await db.execute(
            select(
                func.count(Camera.id),
                func.count().filter(Camera.dernier_heartbeat >= seuil_en_ligne),
            ).select_from(Camera)
        )
    ).one()

    return IndicateursComptage(
        entrees_jour=totaux[0],
        sorties_jour=totaux[1],
        total_passages=totaux[0] + totaux[1],
        visiteurs_uniques_jour=totaux[2],
        visiteurs_recidives_jour=totaux[3],
        personnel_exclu_jour=totaux[4],
        cameras_total=nb_total_cam,
        cameras_en_ligne=nb_en_ligne,
    )


# ---------------------------------------------------------------------------
# Préparation des exports Excel / PDF
# ---------------------------------------------------------------------------


def lignes_export_passages(passages: Sequence[PassageComptage]) -> list[list[Any]]:
    """Génère les lignes pour l'export Excel / PDF."""
    lignes: list[list[Any]] = []
    for p in passages:
        nom_entree = p.camera.libelle_affiche if p.camera else p.master_sn
        lignes.append(
            [
                p.horodatage_debut,
                p.master_sn,
                nom_entree,
                p.entrees,
                p.sorties,
                p.visiteurs_uniques,
                p.visiteurs_recidives,
                p.personnel_exclu,
                p.passants,
            ]
        )
    return lignes


def filtres_export_passages(parametres: ParametresListe) -> list[tuple[str, str]]:
    filtres: list[tuple[str, str]] = []
    if sn := parametres.filtres.get("camera_sn"):
        filtres.append(("Caméra (SN)", sn))
    if date_str := parametres.filtres.get("date_jour"):
        filtres.append(("Date", date_str))
    if parametres.recherche:
        filtres.append(("Recherche", parametres.recherche))
    return filtres


async def generer_rapport_comptage(
    db: AsyncSession,
    camera_sn: str | None = None,
    date_debut: str | None = None,
    date_fin: str | None = None,
) -> dict[str, Any]:
    """Génère une synthèse complète pour le rapport de flux (totaux, par caméra, par heure, ratios)."""
    aujourdhui = maintenant().strftime("%Y-%m-%d")
    debut = date_debut or aujourdhui
    fin = date_fin or debut

    conditions = [
        PassageComptage.batch_date >= debut,
        PassageComptage.batch_date <= fin,
    ]
    if camera_sn:
        conditions.append(PassageComptage.master_sn == camera_sn)

    res_totaux = (
        await db.execute(
            select(
                func.coalesce(func.sum(PassageComptage.entrees), 0),
                func.coalesce(func.sum(PassageComptage.sorties), 0),
                func.coalesce(func.sum(PassageComptage.visiteurs_uniques), 0),
                func.coalesce(func.sum(PassageComptage.visiteurs_recidives), 0),
                func.coalesce(func.sum(PassageComptage.personnel_exclu), 0),
                func.coalesce(func.sum(PassageComptage.passants), 0),
                func.coalesce(func.sum(PassageComptage.demi_tours), 0),
            ).where(and_(*conditions))
        )
    ).one()

    entrees, sorties, uniques, recidives, personnel, passants, demi_tours = res_totaux
    total_clients = uniques + recidives
    taux_revisite = round((recidives / total_clients * 100), 1) if total_clients > 0 else 0.0

    cameras = list(await obtenir_cameras(db))
    cameras_map = {c.sn: c for c in cameras}

    # Répartition par caméra
    requete_cams = (
        select(
            PassageComptage.master_sn,
            func.coalesce(func.sum(PassageComptage.entrees), 0).label("entrees"),
            func.coalesce(func.sum(PassageComptage.sorties), 0).label("sorties"),
            func.coalesce(func.sum(PassageComptage.visiteurs_uniques), 0).label("uniques"),
            func.coalesce(func.sum(PassageComptage.personnel_exclu), 0).label("personnel"),
            func.coalesce(func.sum(PassageComptage.demi_tours), 0).label("demi_tours"),
        )
        .where(and_(*conditions))
        .group_by(PassageComptage.master_sn)
    )
    lignes_cams = (await db.execute(requete_cams)).all()
    repartition_cameras = []
    for sn, e, s, u, p, dt in lignes_cams:
        cam_obj = cameras_map.get(sn)
        repartition_cameras.append(
            {
                "sn": sn,
                "nom": cam_obj.libelle_affiche if cam_obj else sn,
                "entrees": e,
                "sorties": s,
                "uniques": u,
                "personnel": p,
                "demi_tours": dt,
                "statut_en_ligne": cam_obj.est_en_ligne if cam_obj else False,
            }
        )

    # Répartition par tranche horaire complète (00:00 -> 23:00)
    requete_heures = (
        select(
            func.extract("hour", PassageComptage.horodatage_debut).label("heure"),
            func.coalesce(func.sum(PassageComptage.entrees), 0).label("entrees"),
            func.coalesce(func.sum(PassageComptage.sorties), 0).label("sorties"),
            func.coalesce(func.sum(PassageComptage.visiteurs_uniques), 0).label("uniques"),
            func.coalesce(func.sum(PassageComptage.demi_tours), 0).label("demi_tours"),
        )
        .where(and_(*conditions))
        .group_by("heure")
    )
    lignes_heures = (await db.execute(requete_heures)).all()
    heures_dict = {int(h): {"entrees": e, "sorties": s, "uniques": u, "demi_tours": dt} for h, e, s, u, dt in lignes_heures}
    repartition_heures = [
        {
            "heure": f"{h:02d}:00",
            "entrees": heures_dict.get(h, {}).get("entrees", 0),
            "sorties": heures_dict.get(h, {}).get("sorties", 0),
            "uniques": heures_dict.get(h, {}).get("uniques", 0),
            "demi_tours": heures_dict.get(h, {}).get("demi_tours", 0),
        }
        for h in range(0, 24)
    ]

    total_cams = len(cameras)
    cams_en_ligne = sum(1 for c in cameras if c.est_en_ligne)

    return {
        "date_debut": debut,
        "date_fin": fin,
        "camera_sn": camera_sn,
        "entrees": entrees,
        "sorties": sorties,
        "visiteurs_uniques": uniques,
        "visiteurs_recidives": recidives,
        "personnel_exclu": personnel,
        "passants": passants,
        "demi_tours": demi_tours,
        "taux_revisite_pct": taux_revisite,
        "repartition_cameras": repartition_cameras,
        "repartition_heures": repartition_heures,
        "total_cameras": total_cams,
        "cameras_en_ligne": cams_en_ligne,
    }

