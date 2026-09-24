"""Schémas Pydantic du tableau de bord."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.historique.model import ActionHistorique


class IndicateursTableauDeBord(BaseModel):
    """Indicateurs clés (vue ADMIN / MANAGER)."""

    utilisateurs_total: int
    utilisateurs_actifs: int
    utilisateurs_verrouilles: int
    connexions_du_jour: int
    actions_7_jours: int


class ActiviteRecente(BaseModel):
    """Entrée récente de l'historique affichée sur le tableau de bord."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    utilisateur_email: str | None
    action: ActionHistorique
    module: str
    description: str


class TableauDeBordGestion(BaseModel):
    """Contenu du tableau de bord ADMIN / MANAGER."""

    indicateurs: IndicateursTableauDeBord
    dernieres_activites: list[ActiviteRecente]
