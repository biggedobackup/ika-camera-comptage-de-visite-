"""Schémas Pydantic du tableau de bord."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.historique.model import ActionHistorique


class IndicateursTableauDeBord(BaseModel):
    """Indicateurs clés d'administration système."""

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


class FlowKPIs(BaseModel):
    """Indicateurs clés du trafic passager du jour (style Foorir)."""

    visiteurs_total: int = 0
    entrees_jour: int = 0
    sorties_jour: int = 0
    clients_uniques: int = 0
    passants: int = 0
    taux_capture_pct: float = 0.0
    personnel_filtre: int = 0
    sejour_moyen_sec: int = 0
    sejour_moyen_texte: str = "0s"
    clients_recidives: int = 0
    taux_revisite_pct: float = 0.0
    cameras_total: int = 0
    cameras_en_ligne: int = 0


class ComparatifKPI(BaseModel):
    """Comparatifs temporels du flux."""

    hier: int = 0
    semaine_derniere: int = 0
    mois_dernier: int = 0
    annee: int = 0


class TrancheHoraire(BaseModel):
    """Point horaire pour le graphique Flow Trend."""

    heure: str
    entrees: int = 0
    sorties: int = 0
    uniques: int = 0


class DemographieRatio(BaseModel):
    """Répartition IA des visiteurs (genre, âge, structure)."""

    hommes: int = 0
    femmes: int = 0
    inconnu: int = 0
    hommes_pct: float = 0.0
    femmes_pct: float = 0.0
    inconnu_pct: float = 0.0
    kids: int = 0
    youth: int = 0
    prime: int = 0
    middle: int = 0
    seniors: int = 0
    kids_pct: float = 0.0
    youth_pct: float = 0.0
    prime_pct: float = 0.0
    middle_pct: float = 0.0
    seniors_pct: float = 0.0
    structure_clients: int = 0
    structure_personnel: int = 0


class DwellTimeStats(BaseModel):
    """Segmentation du temps de présence en boutique."""

    moins_1min: int = 0
    entre_1_5min: int = 0
    entre_5_15min: int = 0
    entre_15_30min: int = 0
    plus_30min: int = 0
    pct_moins_1min: float = 0.0
    pct_plus_30min: float = 0.0


class CameraResume(BaseModel):
    """Résumé synthétique d'une caméra connectée."""

    sn: str
    nom: str
    emplacement: str | None = None
    entrees: int = 0
    sorties: int = 0
    statut_en_ligne: bool = False


class TableauDeBordGestion(BaseModel):
    """Contenu complet du tableau de bord d'analyse de flux."""

    indicateurs: IndicateursTableauDeBord
    dernieres_activites: list[ActiviteRecente]
    flux: FlowKPIs
    comparatifs: ComparatifKPI
    heures: list[TrancheHoraire]
    demographie: DemographieRatio
    dwell_time: DwellTimeStats
    cameras: list[CameraResume]
