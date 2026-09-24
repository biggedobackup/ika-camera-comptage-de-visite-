"""Moteur SQLAlchemy asynchrone, classe de base des modèles et dépendance de session."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, Uuid, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import settings

# Noms de contraintes déterministes (migrations Alembic reproductibles).
CONVENTION_NOMMAGE = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def maintenant() -> datetime:
    """Date et heure courantes en UTC (timezone-aware)."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Classe de base de tous les modèles."""

    metadata = MetaData(naming_convention=CONVENTION_NOMMAGE)


class UUIDPKMixin:
    """Clé primaire UUID générée côté application."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class HorodatageMixin:
    """Colonnes created_at / updated_at (valeurs posées côté Python : aucun rechargement async)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=maintenant, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=maintenant,
        server_default=func.now(),
        onupdate=maintenant,
        nullable=False,
    )


engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Dépendance FastAPI : une session par requête.

    Les services valident explicitement avec ``await db.commit()`` ; tout ce qui n'est pas validé
    est annulé à la fermeture de la session.
    """
    async with SessionLocal() as session:
        yield session
