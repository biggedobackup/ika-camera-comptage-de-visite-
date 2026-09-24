"""Validation des formulaires HTML avec Pydantic et traduction des erreurs en français."""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

CHAMP_GENERAL = "_general"

_MESSAGES: dict[str, str] = {
    "missing": "Ce champ est obligatoire.",
    "string_type": "Ce champ est obligatoire.",
    "string_too_long": "Ce champ doit contenir au plus {max_length} caractères.",
    "string_pattern_mismatch": "Le format saisi est invalide.",
    "enum": "La valeur choisie n'est pas autorisée.",
    "literal_error": "La valeur choisie n'est pas autorisée.",
    "int_parsing": "Veuillez saisir un nombre entier.",
    "int_type": "Veuillez saisir un nombre entier.",
    "float_parsing": "Veuillez saisir un nombre.",
    "decimal_parsing": "Veuillez saisir un nombre.",
    "bool_parsing": "Valeur invalide.",
    "uuid_parsing": "Identifiant invalide.",
    "date_parsing": "Veuillez saisir une date valide.",
    "date_from_datetime_parsing": "Veuillez saisir une date valide.",
    "datetime_parsing": "Veuillez saisir une date et une heure valides.",
    "greater_than_equal": "La valeur doit être supérieure ou égale à {ge}.",
    "less_than_equal": "La valeur doit être inférieure ou égale à {le}.",
}


def _message(erreur: Mapping[str, Any]) -> str:
    type_erreur = erreur.get("type", "")
    contexte = erreur.get("ctx") or {}
    if type_erreur == "string_too_short":
        minimum = contexte.get("min_length", 1)
        if minimum <= 1:
            return "Ce champ est obligatoire."
        return f"Ce champ doit contenir au moins {minimum} caractères."
    if type_erreur == "value_error":
        if "reason" in contexte:  # EmailStr (email-validator)
            return "L'adresse e-mail saisie est invalide."
        return str(erreur.get("msg", "")).removeprefix("Value error, ") or "Valeur invalide."
    if type_erreur in _MESSAGES:
        try:
            return _MESSAGES[type_erreur].format(**contexte)
        except (KeyError, IndexError):
            return "Valeur invalide."
    # Erreurs personnalisées (PydanticCustomError) : message déjà rédigé en français.
    return str(erreur.get("msg") or "Valeur invalide.")


def erreurs_formulaire(exc: ValidationError) -> dict[str, str]:
    """{nom_du_champ: message en français}. Erreurs sans champ (validateur de modèle) → clé « _general »."""
    erreurs: dict[str, str] = {}
    for erreur in exc.errors():
        localisation = erreur.get("loc") or ()
        champ = str(localisation[0]) if localisation else CHAMP_GENERAL
        erreurs.setdefault(champ, _message(erreur))
    return erreurs


from typing import TypeVar

M = TypeVar("M", bound=BaseModel)


def valider(schema: type[M], donnees: Mapping[str, Any]) -> tuple[M | None, dict[str, str]]:
    """Valide des données de formulaire : (instance, {}) si valides, sinon (None, erreurs en français)."""
    try:
        return schema.model_validate(dict(donnees)), {}
    except ValidationError as exc:
        return None, erreurs_formulaire(exc)
