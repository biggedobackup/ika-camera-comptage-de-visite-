"""Schémas Pydantic pour la validation des données caméra et les vues de comptage."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Payloads montants (Uplink) reçus depuis les caméras HX-CCD21
# ---------------------------------------------------------------------------


class TimezoneInfo(BaseModel):
    name: str | None = None
    utc_offset_seconds: int | None = None
    is_dst: bool | None = None


class EventCounts(BaseModel):
    enter: int = 0
    leave: int = 0
    pass_by: int = 0
    turn_back: int = 0


class StatsBlock(BaseModel):
    count: int = 0
    repeat: int = 0
    breakdowns: dict[str, list[dict[str, Any]]] | None = None


class NonCustomerBlock(BaseModel):
    count: int = 0
    breakdowns: dict[str, list[dict[str, Any]]] | None = None


class DwellStatsBlock(BaseModel):
    count: int = 0
    breakdowns: dict[str, list[dict[str, Any]]] | None = None


class IntervalAggregatePayload(BaseModel):
    """Payload V1.0 : Données agrégées minute par minute (POST /api/passenger-flow/interval-aggregate)."""

    schema_version: str = "1.0"
    type: str = "interval_aggregate"
    master_sn: str
    device_sns: list[str] = Field(default_factory=list)
    timezone: TimezoneInfo | dict[str, Any] = Field(default_factory=dict)
    batch_date: str  # YYYY-MM-DD
    stat_basis: str = "enter"
    revision: int
    interval_s: int = 60
    start_ts_s: int
    end_ts_s: int
    event_counts: EventCounts = Field(default_factory=EventCounts)
    raw_stats: StatsBlock = Field(default_factory=StatsBlock)
    final_stats: StatsBlock = Field(default_factory=StatsBlock)
    non_customer: NonCustomerBlock = Field(default_factory=NonCustomerBlock)
    dwell_stats: DwellStatsBlock = Field(default_factory=DwellStatsBlock)

    model_config = ConfigDict(extra="allow")


class HeartbeatBusiness(BaseModel):
    batch_generation: int | None = None
    batch_date: str | None = None
    state: str | None = None


class DeviceStatusPayload(BaseModel):
    """Payload V1.0 : Heartbeat d'état du matériel (POST /api/passenger-flow/device-status)."""

    schema_version: str = "1.0"
    type: str = "device_status"
    sn: str
    network_role: str = "master"
    ts: int
    timezone: TimezoneInfo | dict[str, Any] = Field(default_factory=dict)
    business: HeartbeatBusiness | dict[str, Any] = Field(default_factory=dict)
    network: dict[str, Any] = Field(default_factory=dict)
    faults: list[Any] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Schémas de gestion et d'affichage
# ---------------------------------------------------------------------------


class CameraCreation(BaseModel):
    sn: str = Field(..., min_length=3, max_length=64, description="Numéro de série unique de la caméra")
    nom: str | None = Field(None, max_length=100, description="Nom convivial de l'entrée")
    emplacement: str | None = Field(None, max_length=100, description="Emplacement physique")
    ip_address: str | None = Field(None, max_length=45, description="Adresse IP sur le réseau local")
    mac_address: str | None = Field(None, max_length=30, description="Adresse MAC")
    modele: str = Field("HX-CCD21", max_length=50, description="Modèle matériel")
    role_reseau: str = Field("master", max_length=20, description="Rôle réseau (master / slave / client)")
    version_logiciel: str | None = Field(None, max_length=50, description="Version de firmware")


class CameraModification(BaseModel):
    nom: str | None = Field(None, max_length=100)
    emplacement: str | None = Field(None, max_length=100)
    ip_address: str | None = Field(None, max_length=45)
    mac_address: str | None = Field(None, max_length=30)
    modele: str = Field("HX-CCD21", max_length=50)
    role_reseau: str = Field("master", max_length=20)
    version_logiciel: str | None = Field(None, max_length=50)


class CameraReponse(BaseModel):
    id: uuid.UUID
    sn: str
    nom: str | None = None
    emplacement: str | None = None
    ip_address: str | None = None
    modele: str
    statut_en_ligne: bool
    dernier_heartbeat: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class IndicateursComptage(BaseModel):
    entrees_jour: int = 0
    sorties_jour: int = 0
    visiteurs_uniques_jour: int = 0
    visiteurs_recidives_jour: int = 0
    personnel_exclu_jour: int = 0
    cameras_total: int = 0
    cameras_en_ligne: int = 0
