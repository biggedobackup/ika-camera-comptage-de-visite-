"""Modèles d'authentification : jetons JWT révoqués et jetons de réinitialisation de mot de passe."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UUIDPKMixin, maintenant


class JetonRevoque(Base):
    """JWT révoqué (déconnexion) : refusé jusqu'à son expiration naturelle."""

    __tablename__ = "jetons_revoques"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expire_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=maintenant, server_default=func.now(), nullable=False
    )


class JetonReinitialisation(UUIDPKMixin, Base):
    """Jeton de réinitialisation de mot de passe (stocké haché SHA-256, usage unique)."""

    __tablename__ = "jetons_reinitialisation"

    utilisateur_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("utilisateurs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    jeton_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expire_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    utilise_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=maintenant, server_default=func.now(), nullable=False
    )

    @property
    def est_valide(self) -> bool:
        """Vrai si le jeton n'a pas été utilisé et n'est pas expiré."""
        return self.utilise_le is None and self.expire_le > maintenant()
