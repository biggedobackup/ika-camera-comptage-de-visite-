"""Modèle du journal d'audit (lecture seule : alimenté uniquement par historique.services.journaliser)."""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UUIDPKMixin, maintenant


class ActionHistorique(enum.StrEnum):
    """Types d'actions journalisées."""

    CREATION = "CREATION"
    MODIFICATION = "MODIFICATION"
    SUPPRESSION = "SUPPRESSION"
    CONNEXION = "CONNEXION"
    DECONNEXION = "DECONNEXION"
    ECHEC_CONNEXION = "ECHEC_CONNEXION"
    VERROUILLAGE = "VERROUILLAGE"
    INSCRIPTION = "INSCRIPTION"
    OTP_ACTIVATION = "OTP_ACTIVATION"
    OTP_DESACTIVATION = "OTP_DESACTIVATION"
    DEMANDE_REINITIALISATION_MOT_DE_PASSE = "DEMANDE_REINITIALISATION_MOT_DE_PASSE"
    REINITIALISATION_MOT_DE_PASSE = "REINITIALISATION_MOT_DE_PASSE"
    CHANGEMENT_MOT_DE_PASSE = "CHANGEMENT_MOT_DE_PASSE"

    @property
    def libelle(self) -> str:
        return LIBELLES_ACTIONS[self]


LIBELLES_ACTIONS: dict[ActionHistorique, str] = {
    ActionHistorique.CREATION: "Création",
    ActionHistorique.MODIFICATION: "Modification",
    ActionHistorique.SUPPRESSION: "Suppression",
    ActionHistorique.CONNEXION: "Connexion",
    ActionHistorique.DECONNEXION: "Déconnexion",
    ActionHistorique.ECHEC_CONNEXION: "Échec de connexion",
    ActionHistorique.VERROUILLAGE: "Verrouillage du compte",
    ActionHistorique.INSCRIPTION: "Inscription",
    ActionHistorique.OTP_ACTIVATION: "Activation de la double authentification",
    ActionHistorique.OTP_DESACTIVATION: "Désactivation de la double authentification",
    ActionHistorique.DEMANDE_REINITIALISATION_MOT_DE_PASSE: "Demande de réinitialisation du mot de passe",
    ActionHistorique.REINITIALISATION_MOT_DE_PASSE: "Réinitialisation du mot de passe",
    ActionHistorique.CHANGEMENT_MOT_DE_PASSE: "Changement de mot de passe",
}


class Historique(UUIDPKMixin, Base):
    """Entrée du journal d'audit."""

    __tablename__ = "historique"

    utilisateur_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("utilisateurs.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # Copie de l'e-mail : l'entrée reste lisible si l'utilisateur est supprimé.
    utilisateur_email: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    action: Mapped[ActionHistorique] = mapped_column(
        Enum(ActionHistorique, name="action_historique", native_enum=False, length=50, validate_strings=True),
        index=True,
        nullable=False,
    )
    module: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    objet_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    donnees_avant: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    donnees_apres: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    adresse_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=maintenant, server_default=func.now(), index=True, nullable=False
    )
