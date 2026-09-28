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


from pydantic import BaseModel, ConfigDict, Field, field_validator


class CameraCreation(BaseModel):
    sn: str = Field(..., min_length=3, max_length=64, description="Numéro de série unique de la caméra")
    nom: str | None = Field(None, max_length=100, description="Nom convivial de l'entrée")
    emplacement: str | None = Field(None, max_length=100, description="Emplacement physique")
    ip_address: str | None = Field(None, max_length=45, description="Adresse IP sur le réseau local")
    mac_address: str | None = Field(None, max_length=30, description="Adresse MAC")
    modele: str = Field("HX-CCD21", max_length=50, description="Modèle matériel")
    role_reseau: str = Field("master", max_length=20, description="Rôle réseau (master / slave / client)")
    version_logiciel: str | None = Field(None, max_length=50, description="Version de firmware")
    statut_en_ligne: bool = Field(False, description="État en ligne ou actif")
    hauteur_installation: int | None = Field(None, ge=50, le=800, description="Hauteur d'installation en cm")
    hauteur_filtrage: int | None = Field(None, ge=30, le=400, description="Hauteur minimale de filtrage en cm")
    mode_enfant: bool = Field(False, description="Activer la détection spécifique des enfants")
    sens_comptage: str = Field("normal", max_length=20, description="Sens de circulation")
    intervalle_envoi: int = Field(60, ge=10, le=3600, description="Intervalle d'agrégation en secondes")
    notes: str | None = Field(None, max_length=500, description="Notes et consignes d'installation")

    @field_validator("sn", "nom", "emplacement", "ip_address", "mac_address", "modele", "role_reseau", "version_logiciel", "sens_comptage", "notes", mode="before")
    @classmethod
    def vider_chaines_vides_creation(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            return v if v else None
        return v

    @field_validator("hauteur_installation", "hauteur_filtrage", mode="before")
    @classmethod
    def convertir_entiers_creation(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        return int(v)

    @field_validator("intervalle_envoi", mode="before")
    @classmethod
    def convertir_intervalle_creation(cls, v: Any) -> Any:
        if v is None or v == "":
            return 60
        return int(v)

    @field_validator("statut_en_ligne", "mode_enfant", mode="before")
    @classmethod
    def convertir_booleens_creation(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "on", "yes", "oui")
        return bool(v)


class CameraModification(BaseModel):
    sn: str | None = Field(None, min_length=3, max_length=64, description="Numéro de série unique")
    nom: str | None = Field(None, max_length=100)
    emplacement: str | None = Field(None, max_length=100)
    ip_address: str | None = Field(None, max_length=45)
    mac_address: str | None = Field(None, max_length=30)
    modele: str = Field("HX-CCD21", max_length=50)
    role_reseau: str = Field("master", max_length=20)
    version_logiciel: str | None = Field(None, max_length=50)
    statut_en_ligne: bool = Field(False)
    hauteur_installation: int | None = Field(None, ge=50, le=800)
    hauteur_filtrage: int | None = Field(None, ge=30, le=400)
    mode_enfant: bool = Field(False)
    sens_comptage: str = Field("normal", max_length=20)
    intervalle_envoi: int = Field(60, ge=10, le=3600)
    notes: str | None = Field(None, max_length=500)

    @field_validator("sn", "nom", "emplacement", "ip_address", "mac_address", "modele", "role_reseau", "version_logiciel", "sens_comptage", "notes", mode="before")
    @classmethod
    def vider_chaines_vides_modification(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            return v if v else None
        return v

    @field_validator("hauteur_installation", "hauteur_filtrage", mode="before")
    @classmethod
    def convertir_entiers_modification(cls, v: Any) -> Any:
        if v is None or v == "":
            return None
        return int(v)

    @field_validator("intervalle_envoi", mode="before")
    @classmethod
    def convertir_intervalle_modification(cls, v: Any) -> Any:
        if v is None or v == "":
            return 60
        return int(v)

    @field_validator("statut_en_ligne", "mode_enfant", mode="before")
    @classmethod
    def convertir_booleens_modification(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "on", "yes", "oui")
        return bool(v)


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
