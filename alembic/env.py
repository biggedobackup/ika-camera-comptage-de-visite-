"""Environnement Alembic (migrations synchrones via psycopg2)."""

from logging.config import fileConfig

from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

from alembic import context
from app.core.config import settings
from app.core.database import Base

# Import de tous les modèles pour que leurs tables soient présentes dans Base.metadata.
import app.auth.model  # noqa: F401,E402
import app.camera.model  # noqa: F401,E402
import app.historique.model  # noqa: F401,E402
import app.utilisateur.model  # noqa: F401,E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def url_synchrone() -> str:
    """DATABASE_URL avec le pilote psycopg2 à la place d'asyncpg."""
    url = make_url(settings.DATABASE_URL)
    if url.drivername in ("postgresql+asyncpg", "postgresql"):
        url = url.set(drivername="postgresql+psycopg2")
    return url.render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    """Génère le SQL sans connexion à la base."""
    context.configure(
        url=url_synchrone(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Applique les migrations sur la base."""
    moteur = create_engine(url_synchrone(), poolclass=pool.NullPool)
    with moteur.connect() as connexion:
        context.configure(connection=connexion, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    moteur.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
