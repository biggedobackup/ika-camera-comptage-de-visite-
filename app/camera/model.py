"""Modèles du module caméra et comptage de flux (HX-CCD21)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, HorodatageMixin, UUIDPKMixin, maintenant


class Camera(UUIDPKMixin, HorodatageMixin, Base):
    """Caméra 3D de comptage de personnes (HX-CCD21)."""

    __tablename__ = "cameras"

    sn: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    nom: Mapped[str | None] = mapped_column(String(100), nullable=True)
    emplacement: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    mac_address: Mapped[str | None] = mapped_column(String(30), nullable=True)
    modele: Mapped[str] = mapped_column(String(50), default="HX-CCD21", nullable=False)
    version_logiciel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    role_reseau: Mapped[str] = mapped_column(String(20), default="master", nullable=False)  # master / slave / client
    statut_en_ligne: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dernier_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    configuration: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    passages: Mapped[list["PassageComptage"]] = relationship(
        "PassageComptage", back_populates="camera", cascade="all, delete-orphan"
    )
    heartbeats: Mapped[list["CameraHeartbeat"]] = relationship(
        "CameraHeartbeat", back_populates="camera", cascade="all, delete-orphan"
    )

    @property
    def libelle_affiche(self) -> str:
        """Nom configuré ou SN si non renseigné."""
        return self.nom or self.emplacement or f"Caméra {self.sn}"

    @property
    def est_en_ligne(self) -> bool:
        """Indique si la caméra a émis un signal dans les 3 dernières minutes (180s)."""
        if not self.dernier_heartbeat:
            return False
        hb = self.dernier_heartbeat
        if hb.tzinfo is None:
            hb = hb.replace(tzinfo=UTC)
        diff = (maintenant() - hb).total_seconds()
        return -60 <= diff <= 180

    @property
    def hauteur_installation(self) -> int | None:
        """Hauteur d'installation en centimètres (ex. 280 cm)."""
        return (self.configuration or {}).get("hauteur_installation")

    @property
    def hauteur_filtrage(self) -> int | None:
        """Hauteur de filtrage en centimètres (ex. 110 cm)."""
        return (self.configuration or {}).get("hauteur_filtrage")

    @property
    def mode_enfant(self) -> bool:
        """Indique si le mode détection d'enfants est activé."""
        return bool((self.configuration or {}).get("mode_enfant", False))

    @property
    def sens_comptage(self) -> str:
        """Sens de circulation configuré (normal ou inverse)."""
        return (self.configuration or {}).get("sens_comptage", "normal")

    @property
    def intervalle_envoi(self) -> int:
        """Intervalle d'agrégation et transmission en secondes (par défaut 60s)."""
        val = (self.configuration or {}).get("intervalle_envoi")
        try:
            return int(val) if val is not None else 60
        except (ValueError, TypeError):
            return 60

    @property
    def notes(self) -> str | None:
        """Notes techniques et remarques d'installation."""
        return (self.configuration or {}).get("notes")


class PassageComptage(UUIDPKMixin, Base):
    """Statistiques de passage agrégées par minute (protocole HX-CCD21)."""

    __tablename__ = "passages_comptage"

    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("cameras.id", ondelete="SET NULL"), index=True, nullable=True
    )
    master_sn: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    batch_date: Mapped[str] = mapped_column(String(10), index=True, nullable=False)  # YYYY-MM-DD
    stat_basis: Mapped[str] = mapped_column(String(10), default="enter", nullable=False)  # enter / leave
    revision: Mapped[int] = mapped_column(BigInteger, nullable=False)  # Timestamp du moment de calcul
    interval_s: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    start_ts_s: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)  # Epoch Unix début
    end_ts_s: Mapped[int] = mapped_column(BigInteger, nullable=False)  # Epoch Unix fin
    horodatage_debut: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)

    # Flux bruts (event_counts)
    entrees: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sorties: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passants: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # pass_by
    demi_tours: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # turn_back

    # Données IA dédoublées (final_stats / non_customer)
    visiteurs_uniques: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # Nouveaux clients
    visiteurs_recidives: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # Déjà venus ce jour
    personnel_exclu: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # Employés/livreurs filtrés
    duree_sejour_moyenne_sec: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Répartitions détaillées (breakdowns JSON)
    repartition_age_genre: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    repartition_taille: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    repartition_sejour: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    donnees_brutes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=maintenant, server_default=func.now(), index=True, nullable=False
    )

    camera: Mapped[Camera | None] = relationship("Camera", back_populates="passages")

    __table_args__ = (
        UniqueConstraint("master_sn", "batch_date", "start_ts_s", name="uq_passage_sn_date_debut"),
    )


class CameraHeartbeat(UUIDPKMixin, Base):
    """Journal des pings de santé émis par chaque caméra."""

    __tablename__ = "camera_heartbeats"

    camera_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("cameras.id", ondelete="SET NULL"), index=True, nullable=True
    )
    camera_sn: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    ts: Mapped[int] = mapped_column(BigInteger, nullable=False)
    etat: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    donnees: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=maintenant, server_default=func.now(), index=True, nullable=False
    )

    camera: Mapped[Camera | None] = relationship("Camera", back_populates="heartbeats")
