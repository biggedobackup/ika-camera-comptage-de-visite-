"""Schémas Pydantic du module historique (lecture seule)."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from app.historique.model import ActionHistorique


class FiltresHistorique(BaseModel):
    """Filtres de la liste et des exports : ?du=&au=&action=&module= (valeur absente = pas de filtre).

    `du` et `au` sont des dates (AAAA-MM-JJ, UTC), bornes incluses.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    du: date | None = None
    au: date | None = None
    action: ActionHistorique | None = None
    module: str | None = Field(default=None, max_length=50, pattern=r"^[a-z0-9_]+$")

    @model_validator(mode="after")
    def verifier_periode(self) -> "FiltresHistorique":
        if self.du is not None and self.au is not None and self.du > self.au:
            raise PydanticCustomError(
                "periode_invalide",
                "La date « Du » doit être antérieure ou égale à la date « Au ». La période n'a pas été appliquée.",
            )
        return self


class LigneComparaison(BaseModel):
    """Une ligne du tableau « données avant / après » de la page détail."""

    champ: str
    libelle: str
    avant: str | None = None
    apres: str | None = None
    modifie: bool = False


class ComparaisonDonnees(BaseModel):
    """Données avant/après d'une entrée, prêtes à afficher."""

    lignes: list[LigneComparaison]
    avec_avant: bool
    avec_apres: bool
