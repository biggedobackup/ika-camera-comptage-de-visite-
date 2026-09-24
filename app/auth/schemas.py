"""Schémas Pydantic du module auth (validation des formulaires, messages en français).

Les mots de passe ne sont jamais nettoyés (pas de suppression des espaces) : ils sont vérifiés tels
que saisis. Les types `Email`, `NomComplet` et `Telephone` sont réutilisables par d'autres modules.
"""

import re
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    EmailStr,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
)
from pydantic_core import PydanticCustomError

from app.core.security import MotDePasse

LONGUEUR_MAX_SAISIE_MOT_DE_PASSE = 1024  # garde-fou : la politique limite de toute façon à 72 octets
LONGUEUR_CODE_OTP = 6

_MOTIF_TELEPHONE = re.compile(r"\+?[0-9 ().-]+")
_MOTIF_CODE_OTP = re.compile(rf"[0-9]{{{LONGUEUR_CODE_OTP}}}")


# ---------------------------------------------------------------------------
# Types réutilisables
# ---------------------------------------------------------------------------


def _email_obligatoire(valeur: Any) -> Any:
    """Supprime les espaces autour de l'e-mail ; message clair si le champ est vide."""
    if isinstance(valeur, str):
        valeur = valeur.strip()
        if not valeur:
            raise PydanticCustomError("champ_obligatoire", "Veuillez saisir votre adresse e-mail.")
    return valeur


def _en_minuscules(valeur: str) -> str:
    return valeur.lower()


# Adresse e-mail valide, sans espaces, stockée et comparée en minuscules.
Email = Annotated[EmailStr, BeforeValidator(_email_obligatoire), AfterValidator(_en_minuscules)]

NomComplet = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=150)]


def _vide_vers_none(valeur: Any) -> Any:
    if isinstance(valeur, str):
        valeur = valeur.strip()
        return valeur or None
    return valeur


def _valider_telephone(valeur: str | None) -> str | None:
    if valeur is None:
        return None
    nombre_chiffres = sum(c.isdigit() for c in valeur)
    if len(valeur) > 30 or not _MOTIF_TELEPHONE.fullmatch(valeur) or not 6 <= nombre_chiffres <= 20:
        raise PydanticCustomError(
            "telephone",
            "Numéro de téléphone invalide : utilisez uniquement des chiffres, des espaces et les "
            "caractères + - . ( ) (6 chiffres minimum, 30 caractères maximum).",
        )
    return valeur


# Téléphone facultatif (chaîne vide → None).
Telephone = Annotated[str | None, BeforeValidator(_vide_vers_none), AfterValidator(_valider_telephone)]

# Mot de passe saisi pour vérification (connexion, mot de passe actuel) : aucune politique appliquée.
MotDePasseSaisi = Annotated[str, Field(min_length=1, max_length=LONGUEUR_MAX_SAISIE_MOT_DE_PASSE)]


def _verifier_confirmation(confirmation: str, info: ValidationInfo, champ: str) -> str:
    """Erreur sur le champ « confirmation » si elle diffère du mot de passe (déjà valide)."""
    mot_de_passe = info.data.get(champ)
    if mot_de_passe is not None and confirmation != mot_de_passe:
        raise PydanticCustomError(
            "confirmation_mot_de_passe", "La confirmation ne correspond pas au mot de passe saisi."
        )
    return confirmation


# ---------------------------------------------------------------------------
# Connexion et double authentification
# ---------------------------------------------------------------------------


class SchemaConnexion(BaseModel):
    email: Email
    mot_de_passe: MotDePasseSaisi


class SchemaCodeOtp(BaseModel):
    """Code TOTP à 6 chiffres (les espaces saisis sont ignorés : « 123 456 » est accepté)."""

    code: str

    @field_validator("code", mode="before")
    @classmethod
    def _retirer_espaces(cls, valeur: Any) -> Any:
        return re.sub(r"\s+", "", valeur) if isinstance(valeur, str) else valeur

    @field_validator("code")
    @classmethod
    def _verifier_format(cls, valeur: str) -> str:
        if not valeur:
            raise PydanticCustomError("champ_obligatoire", "Veuillez saisir le code à 6 chiffres.")
        if not _MOTIF_CODE_OTP.fullmatch(valeur):
            raise PydanticCustomError(
                "code_otp", "Le code de vérification doit contenir exactement 6 chiffres."
            )
        return valeur


class SchemaDesactivationOtp(BaseModel):
    mot_de_passe_actuel: MotDePasseSaisi


# ---------------------------------------------------------------------------
# Inscription
# ---------------------------------------------------------------------------


class SchemaInscription(BaseModel):
    nom_complet: NomComplet
    email: Email
    telephone: Telephone = None
    mot_de_passe: MotDePasse
    confirmation: str

    @field_validator("confirmation")
    @classmethod
    def _confirmation(cls, valeur: str, info: ValidationInfo) -> str:
        return _verifier_confirmation(valeur, info, "mot_de_passe")


# ---------------------------------------------------------------------------
# Mot de passe oublié / réinitialisation
# ---------------------------------------------------------------------------


class SchemaMotDePasseOublie(BaseModel):
    email: Email


class SchemaReinitialisation(BaseModel):
    mot_de_passe: MotDePasse
    confirmation: str

    @field_validator("confirmation")
    @classmethod
    def _confirmation(cls, valeur: str, info: ValidationInfo) -> str:
        return _verifier_confirmation(valeur, info, "mot_de_passe")


# ---------------------------------------------------------------------------
# Profil
# ---------------------------------------------------------------------------


class SchemaProfil(BaseModel):
    nom_complet: NomComplet
    telephone: Telephone = None


class SchemaChangementMotDePasse(BaseModel):
    mot_de_passe_actuel: MotDePasseSaisi
    nouveau_mot_de_passe: MotDePasse
    confirmation: str

    @field_validator("nouveau_mot_de_passe")
    @classmethod
    def _different_de_l_actuel(cls, valeur: str, info: ValidationInfo) -> str:
        if valeur == info.data.get("mot_de_passe_actuel"):
            raise PydanticCustomError(
                "mot_de_passe_identique",
                "Le nouveau mot de passe doit être différent du mot de passe actuel.",
            )
        return valeur

    @field_validator("confirmation")
    @classmethod
    def _confirmation(cls, valeur: str, info: ValidationInfo) -> str:
        return _verifier_confirmation(valeur, info, "nouveau_mot_de_passe")
