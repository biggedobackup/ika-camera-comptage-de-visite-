"""Configuration de l'application chargée depuis les variables d'environnement et le fichier .env."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

RACINE_PROJET = Path(__file__).resolve().parents[2]
DOSSIER_APP = RACINE_PROJET / "app"

ENVIRONNEMENTS = ("development", "test", "production")


def _decouper_liste(valeur: object) -> object:
    """Accepte une liste ou une chaîne séparée par des virgules (« a, b, c »)."""
    if isinstance(valeur, str):
        return [element.strip() for element in valeur.split(",") if element.strip()]
    return valeur


class Settings(BaseSettings):
    """Paramètres de l'application (Pydantic Settings)."""

    model_config = SettingsConfigDict(
        env_file=RACINE_PROJET / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # Application
    APP_NAME: str = "IKA COMPTEUR"
    APP_ENV: str = "production"
    APP_DEBUG: bool = False
    APP_BASE_URL: str = "http://127.0.0.1:8000"

    # Sécurité
    SECRET_KEY: str = Field(min_length=32)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60, ge=1)
    SESSION_EXPIRE_MINUTES: int = Field(default=480, ge=1)
    PASSWORD_RESET_EXPIRE_MINUTES: int = Field(default=30, ge=1)
    # None = automatique : True en production, False sinon (développement en http://).
    COOKIE_SECURE: bool | None = None
    ALLOWED_HOSTS: Annotated[list[str], NoDecode] = [
        "127.0.0.1",
        "localhost",
        "compteur.ikavisite.com",
        "172.17.18.42",
    ]
    # Vide = uniquement APP_BASE_URL.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = []

    # Base de données
    DATABASE_URL: str

    # Messagerie
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_TLS: bool = True
    MAIL_FROM: str = "no-reply@ikacompteur.com"
    MAIL_FROM_NAME: str = "IKA COMPTEUR"

    # Premier administrateur (script scripts/creer_premier_admin.py)
    FIRST_ADMIN_EMAIL: str = ""
    FIRST_ADMIN_PASSWORD: str = ""
    FIRST_ADMIN_NAME: str = "Administrateur"

    @field_validator("ALLOWED_HOSTS", "CORS_ORIGINS", mode="before")
    @classmethod
    def _valider_listes(cls, valeur: object) -> object:
        return _decouper_liste(valeur)

    @field_validator("COOKIE_SECURE", mode="before")
    @classmethod
    def _valider_cookie_secure(cls, valeur: object) -> object:
        """Valeur vide = automatique."""
        if isinstance(valeur, str) and not valeur.strip():
            return None
        return valeur

    @field_validator("APP_ENV")
    @classmethod
    def _valider_environnement(cls, valeur: str) -> str:
        valeur = valeur.strip().lower()
        if valeur not in ENVIRONNEMENTS:
            raise ValueError(f"APP_ENV doit valoir l'une des valeurs : {', '.join(ENVIRONNEMENTS)}.")
        return valeur

    @model_validator(mode="after")
    def _verifier_production(self) -> "Settings":
        if self.est_production:
            if self.SECRET_KEY.startswith("change-me"):
                raise ValueError("SECRET_KEY doit être remplacée par une valeur aléatoire en production.")
            if self.APP_DEBUG:
                raise ValueError("APP_DEBUG doit valoir false en production.")
        return self

    @property
    def est_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def cookie_secure(self) -> bool:
        """Attribut Secure des cookies (session et JWT)."""
        if self.COOKIE_SECURE is None:
            return self.est_production
        return self.COOKIE_SECURE

    @property
    def cors_origins(self) -> list[str]:
        """Origines CORS autorisées (APP_BASE_URL par défaut)."""
        return self.CORS_ORIGINS or [self.APP_BASE_URL.rstrip("/")]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
