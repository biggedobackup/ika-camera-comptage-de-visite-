"""Modèle User et énumération des rôles."""

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, HorodatageMixin, UUIDPKMixin, maintenant


class Role(enum.StrEnum):
    """Rôles applicatifs."""

    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    UTILISATEUR = "UTILISATEUR"

    @property
    def libelle(self) -> str:
        return LIBELLES_ROLES[self]


LIBELLES_ROLES: dict[Role, str] = {
    Role.ADMIN: "Administrateur",
    Role.MANAGER: "Manager",
    Role.UTILISATEUR: "Utilisateur",
}


class User(UUIDPKMixin, HorodatageMixin, Base):
    """Compte utilisateur."""

    __tablename__ = "utilisateurs"

    nom_complet: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    telephone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    mot_de_passe_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="role_utilisateur", native_enum=False, length=20, validate_strings=True),
        default=Role.UTILISATEUR,
        nullable=False,
    )
    est_actif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Double authentification (secret TOTP chiffré avec Fernet, jamais en clair).
    otp_secret_chiffre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    otp_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Verrouillage après échecs de connexion.
    tentatives_echouees: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    verrouille_jusqua: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    derniere_connexion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def est_verrouille(self) -> bool:
        """Vrai si le compte est verrouillé à cet instant."""
        return self.verrouille_jusqua is not None and self.verrouille_jusqua > maintenant()

    @property
    def minutes_verrouillage_restantes(self) -> int:
        """Minutes restantes avant déverrouillage (arrondi supérieur, 0 si non verrouillé)."""
        if not self.est_verrouille:
            return 0
        secondes = (self.verrouille_jusqua - maintenant()).total_seconds()  # type: ignore[operator]
        return max(1, -(-int(secondes) // 60))

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role})>"
