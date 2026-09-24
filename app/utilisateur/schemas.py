"""Schémas Pydantic du module utilisateur (formulaires de création et de modification)."""

import re
from typing import Annotated

from pydantic import BaseModel, EmailStr, StringConstraints, ValidationInfo, field_validator

from app.core.security import MotDePasse
from app.utilisateur.model import Role

LONGUEUR_MAX_EMAIL = 255
LONGUEUR_MAX_TELEPHONE = 30
MIN_CHIFFRES_TELEPHONE = 6
MOTIF_TELEPHONE = re.compile(r"\+?[0-9 ().-]+")

NomComplet = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=150)]
Telephone = Annotated[str, StringConstraints(strip_whitespace=True)] | None


class _ChampsUtilisateur(BaseModel):
    """Champs communs à la création et à la modification d'un compte."""

    nom_complet: NomComplet
    email: EmailStr
    telephone: Telephone = None
    role: Role
    est_actif: bool = False  # case à cocher : absente du formulaire = décochée

    @field_validator("email", mode="before")
    @classmethod
    def _email_renseigne(cls, valeur: object) -> object:
        if isinstance(valeur, str):
            valeur = valeur.strip()
            if not valeur:
                raise ValueError("L'adresse e-mail est obligatoire.")
            if len(valeur) > LONGUEUR_MAX_EMAIL:
                raise ValueError(f"L'adresse e-mail ne doit pas dépasser {LONGUEUR_MAX_EMAIL} caractères.")
        return valeur

    @field_validator("email")
    @classmethod
    def _email_minuscules(cls, valeur: str) -> str:
        return valeur.lower()

    @field_validator("telephone", mode="before")
    @classmethod
    def _telephone_vide(cls, valeur: object) -> object:
        if isinstance(valeur, str) and not valeur.strip():
            return None
        return valeur

    @field_validator("telephone")
    @classmethod
    def _telephone_valide(cls, valeur: str | None) -> str | None:
        if valeur is None:
            return None
        if (
            len(valeur) > LONGUEUR_MAX_TELEPHONE
            or not MOTIF_TELEPHONE.fullmatch(valeur)
            or sum(c.isdigit() for c in valeur) < MIN_CHIFFRES_TELEPHONE
        ):
            raise ValueError(
                f"Le numéro de téléphone est invalide : au moins {MIN_CHIFFRES_TELEPHONE} chiffres, "
                f"{LONGUEUR_MAX_TELEPHONE} caractères au maximum, uniquement des chiffres, des espaces, "
                "le signe + en tête, les signes - . et des parenthèses."
            )
        return valeur


class UtilisateurCreation(_ChampsUtilisateur):
    """Création d'un compte par un administrateur (mot de passe initial obligatoire)."""

    mot_de_passe: MotDePasse
    confirmation_mot_de_passe: str

    @field_validator("confirmation_mot_de_passe")
    @classmethod
    def _confirmation_identique(cls, valeur: str, info: ValidationInfo) -> str:
        mot_de_passe = info.data.get("mot_de_passe")
        if mot_de_passe is not None and valeur != mot_de_passe:
            raise ValueError("La confirmation ne correspond pas au mot de passe saisi.")
        return valeur


class UtilisateurModification(_ChampsUtilisateur):
    """Modification des informations d'un compte par un administrateur (le mot de passe n'est pas modifié ici)."""
