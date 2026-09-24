"""Service de journalisation unique (`journaliser(...)`, appelé par tous les modules)
et lecture du journal (liste filtrée, détail, exports) — le module historique est en lecture seule."""

import enum
import json
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy import Select, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exports import formater_valeur
from app.core.listes import (
    ParametresListe,
    appliquer_recherche,
    appliquer_tri,
    decrire_filtres,
    lire_parametres_liste,
    tout_recuperer,
)
from app.core.security import adresse_ip_client
from app.core.validation import CHAMP_GENERAL, valider
from app.historique.model import ActionHistorique, Historique
from app.historique.schemas import ComparaisonDonnees, FiltresHistorique, LigneComparaison
from app.utilisateur.model import LIBELLES_ROLES, User

# Toute clé contenant l'un de ces fragments est exclue des données journalisées.
FRAGMENTS_SENSIBLES = ("mot_de_passe", "password", "hash", "jeton", "token", "secret", "csrf", "otp_code")

LONGUEUR_MAX_USER_AGENT = 255


def _est_sensible(cle: str) -> bool:
    cle = cle.lower()
    return any(fragment in cle for fragment in FRAGMENTS_SENSIBLES)


def _serialiser(valeur: Any) -> Any:
    """Convertit une valeur en type compatible JSON en retirant récursivement les clés sensibles."""
    if isinstance(valeur, enum.Enum):
        return valeur.value
    if valeur is None or isinstance(valeur, (bool, int, float, str)):
        return valeur
    if isinstance(valeur, (datetime, date)):
        return valeur.isoformat()
    if isinstance(valeur, (uuid.UUID, Decimal)):
        return str(valeur)
    if isinstance(valeur, Mapping):
        return {str(k): _serialiser(v) for k, v in valeur.items() if not _est_sensible(str(k))}
    if isinstance(valeur, (list, tuple, set, frozenset)):
        return [_serialiser(v) for v in valeur]
    return str(valeur)


def nettoyer_donnees(donnees: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Données prêtes à journaliser : JSON, sans mot de passe, hash, jeton ni secret."""
    if donnees is None:
        return None
    return _serialiser(donnees)


def instantane(objet: Any, champs: Iterable[str] | None = None) -> dict[str, Any]:
    """Photographie des colonnes d'un modèle (pour donnees_avant / donnees_apres).

    `champs` : colonnes à retenir (toutes par défaut). Les colonnes sensibles sont toujours exclues.
    À appeler AVANT la modification pour `donnees_avant`, APRÈS pour `donnees_apres`.
    """
    colonnes = [attribut.key for attribut in inspect(objet).mapper.column_attrs]
    retenues = [c for c in (champs if champs is not None else colonnes) if c in colonnes]
    return nettoyer_donnees({c: getattr(objet, c) for c in retenues}) or {}


async def journaliser(
    db: AsyncSession,
    *,
    action: ActionHistorique,
    module: str,
    description: str,
    utilisateur: User | None = None,
    utilisateur_email: str | None = None,
    objet_id: uuid.UUID | str | None = None,
    donnees_avant: Mapping[str, Any] | None = None,
    donnees_apres: Mapping[str, Any] | None = None,
    request: Request | None = None,
) -> Historique:
    """Ajoute une entrée au journal d'audit dans la transaction courante (flush, sans commit).

    L'appelant valide avec `await db.commit()` : l'action et son entrée d'historique sont
    enregistrées ensemble. Pour un échec de connexion sans compte existant, passer
    `utilisateur_email` (e-mail saisi) sans `utilisateur`.
    """
    user_agent = request.headers.get("user-agent") if request is not None else None
    email = utilisateur.email if utilisateur is not None else utilisateur_email
    entree = Historique(
        utilisateur_id=utilisateur.id if utilisateur is not None else None,
        utilisateur_email=email[:255] if email else None,
        action=action,
        module=module,
        objet_id=str(objet_id) if objet_id is not None else None,
        description=description,
        donnees_avant=nettoyer_donnees(donnees_avant),
        donnees_apres=nettoyer_donnees(donnees_apres),
        adresse_ip=adresse_ip_client(request) if request is not None else None,
        user_agent=user_agent[:LONGUEUR_MAX_USER_AGENT] if user_agent else None,
    )
    db.add(entree)
    await db.flush()
    return entree


# ---------------------------------------------------------------------------
# Lecture du journal : libellés, filtres, liste, détail, exports
# ---------------------------------------------------------------------------

LIBELLES_MODULES: dict[str, str] = {
    "auth": "Authentification",
    "utilisateur": "Utilisateurs",
    "historique": "Historique",
}

# Actions mises en évidence (rouge) dans les listes.
ACTIONS_ALERTE: frozenset[ActionHistorique] = frozenset(
    {ActionHistorique.SUPPRESSION, ActionHistorique.ECHEC_CONNEXION, ActionHistorique.VERROUILLAGE}
)

# Liste blanche des colonnes triables (nom du paramètre « tri » → colonne).
COLONNES_TRI = {
    "created_at": Historique.created_at,
    "utilisateur": Historique.utilisateur_email,
    "action": Historique.action,
    "module": Historique.module,
    "description": Historique.description,
    "adresse_ip": Historique.adresse_ip,
}
LIBELLES_TRI = {
    "created_at": "Date",
    "utilisateur": "Utilisateur",
    "action": "Action",
    "module": "Module",
    "description": "Description",
    "adresse_ip": "Adresse IP",
}
NOMS_FILTRES = ("du", "au", "action", "module")
LIBELLES_FILTRES = {"du": "Du", "au": "Au", "action": "Action", "module": "Module"}

OPTIONS_ACTIONS: list[tuple[str, str]] = [(action.value, action.libelle) for action in ActionHistorique]

TITRE_EXPORT = "Historique des actions"
NOM_FICHIER_EXPORT = "historique"
ENTETES_EXPORT = ["Date (UTC)", "Utilisateur", "Action", "Module", "Description", "Objet concerné", "Adresse IP"]
LARGEURS_EXPORT_PDF = [1.5, 2.6, 2.2, 1.4, 4.2, 2.6, 1.4]


def libelle_module(module: str) -> str:
    """Libellé lisible d'un nom de module (« utilisateur » → « Utilisateurs »)."""
    return LIBELLES_MODULES.get(module, module.replace("_", " ").capitalize())


# --- Filtres -----------------------------------------------------------------


def valider_filtres(valeurs: Mapping[str, str]) -> tuple[FiltresHistorique, list[str]]:
    """Valide les filtres de la query string.

    Retourne les filtres valides et, pour chaque filtre invalide (ignoré), un message clair en français.
    """
    donnees = dict(valeurs)
    messages: list[str] = []
    for _ in range(len(NOMS_FILTRES) + 1):
        filtres, erreurs = valider(FiltresHistorique, donnees)
        if filtres is not None:
            return filtres, messages
        for champ, message in erreurs.items():
            if champ == CHAMP_GENERAL:  # période incohérente : les deux dates sont ignorées
                donnees.pop("du", None)
                donnees.pop("au", None)
                messages.append(message)
            else:
                donnees.pop(champ, None)
                messages.append(f"Filtre « {LIBELLES_FILTRES.get(champ, champ)} » ignoré : {message}")
    return FiltresHistorique(), messages


def lire_parametres(request: Request) -> tuple[ParametresListe, FiltresHistorique, list[str]]:
    """Paramètres de la liste, partagés par la liste et les exports.

    Les filtres invalides sont retirés (et signalés) ; les filtres retenus sont normalisés, pour que
    la pagination, le tri et les exports reprennent exactement les filtres appliqués.
    """
    parametres = lire_parametres_liste(
        request,
        colonnes_tri=COLONNES_TRI.keys(),
        tri_defaut="created_at",
        ordre_defaut="desc",
        filtres=NOMS_FILTRES,
    )
    filtres, erreurs = valider_filtres(parametres.filtres)
    retenus: dict[str, str] = {}
    if filtres.du is not None:
        retenus["du"] = filtres.du.isoformat()
    if filtres.au is not None:
        retenus["au"] = filtres.au.isoformat()
    if filtres.action is not None:
        retenus["action"] = filtres.action.value
    if filtres.module:
        retenus["module"] = filtres.module
    return replace(parametres, filtres=retenus), filtres, erreurs


def requete_historique(parametres: ParametresListe, filtres: FiltresHistorique) -> Select:
    """Requête filtrée et triée, partagée par la liste et les exports.

    Recherche (insensible à la casse) : e-mail de l'utilisateur, nom de l'utilisateur, description.
    Période : bornes incluses, en UTC.
    """
    requete = select(Historique)
    if parametres.recherche:
        requete = appliquer_recherche(
            requete.outerjoin(User, Historique.utilisateur_id == User.id),
            parametres.recherche,
            [Historique.utilisateur_email, User.nom_complet, Historique.description],
        )
    if filtres.du is not None:
        requete = requete.where(Historique.created_at >= datetime.combine(filtres.du, time.min, tzinfo=UTC))
    if filtres.au is not None:
        requete = requete.where(Historique.created_at <= datetime.combine(filtres.au, time.max, tzinfo=UTC))
    if filtres.action is not None:
        requete = requete.where(Historique.action == filtres.action)
    if filtres.module:
        requete = requete.where(Historique.module == filtres.module)
    return appliquer_tri(requete, parametres, COLONNES_TRI, departage=Historique.id)


async def options_modules(db: AsyncSession) -> list[tuple[str, str]]:
    """Options du filtre « Module » : modules connus + modules présents dans le journal."""
    presents = (await db.scalars(select(Historique.module).distinct())).all()
    noms = set(presents) | set(LIBELLES_MODULES)
    return sorted(((nom, libelle_module(nom)) for nom in noms), key=lambda option: option[1].lower())


# --- Détail ------------------------------------------------------------------

LIBELLES_CHAMPS: dict[str, str] = {
    "id": "Identifiant",
    "nom_complet": "Nom complet",
    "email": "Adresse e-mail",
    "telephone": "Téléphone",
    "role": "Rôle",
    "est_actif": "Compte actif",
    "otp_active": "Double authentification activée",
    "tentatives_echouees": "Tentatives de connexion échouées",
    "verrouille_jusqua": "Verrouillé jusqu'au",
    "derniere_connexion": "Dernière connexion",
    "created_at": "Créé le",
    "updated_at": "Modifié le",
}
VALEURS_LISIBLES: dict[str, dict[str, str]] = {"role": {role.value: libelle for role, libelle in LIBELLES_ROLES.items()}}

_MOTIF_DATE_HEURE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
_MOTIF_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ABSENT = object()


async def obtenir_entree(db: AsyncSession, entree_id: uuid.UUID) -> Historique | None:
    return await db.get(Historique, entree_id)


async def obtenir_auteur(db: AsyncSession, entree: Historique) -> User | None:
    """Compte auteur de l'action, s'il existe encore."""
    if entree.utilisateur_id is None:
        return None
    return await db.get(User, entree.utilisateur_id)


def libelle_champ(champ: str) -> str:
    return LIBELLES_CHAMPS.get(champ, champ.replace("_", " ").capitalize())


def formater_donnee(champ: str, valeur: Any) -> str | None:
    """Valeur journalisée (JSON) en texte lisible ; None si vide."""
    if valeur is None or valeur == "":
        return None
    if isinstance(valeur, bool):
        return "Oui" if valeur else "Non"
    if isinstance(valeur, str):
        lisible = VALEURS_LISIBLES.get(champ, {}).get(valeur)
        if lisible is not None:
            return lisible
        try:
            if _MOTIF_DATE_HEURE.match(valeur):
                return formater_valeur(datetime.fromisoformat(valeur))
            if _MOTIF_DATE.match(valeur):
                return formater_valeur(date.fromisoformat(valeur))
        except ValueError:
            pass
        return valeur
    if isinstance(valeur, (dict, list)):
        return json.dumps(valeur, ensure_ascii=False, indent=2)
    return str(valeur)


def comparer_donnees(entree: Historique) -> ComparaisonDonnees:
    """Tableau lisible des données avant / après (champs sensibles toujours exclus)."""
    avant = nettoyer_donnees(entree.donnees_avant) or {}
    apres = nettoyer_donnees(entree.donnees_apres) or {}
    avec_avant, avec_apres = bool(avant), bool(apres)
    # JSONB ne conserve pas l'ordre des clés : champs connus d'abord, puis ordre alphabétique.
    ordre = {champ: indice for indice, champ in enumerate(LIBELLES_CHAMPS)}
    champs = sorted(set(avant) | set(apres), key=lambda champ: (ordre.get(champ, len(ordre)), champ))
    lignes = [
        LigneComparaison(
            champ=champ,
            libelle=libelle_champ(champ),
            avant=formater_donnee(champ, avant.get(champ)),
            apres=formater_donnee(champ, apres.get(champ)),
            modifie=avec_avant and avec_apres and avant.get(champ, _ABSENT) != apres.get(champ, _ABSENT),
        )
        for champ in champs
    ]
    return ComparaisonDonnees(lignes=lignes, avec_avant=avec_avant, avec_apres=avec_apres)


# --- Exports -----------------------------------------------------------------


def lignes_export(entrees: Iterable[Historique]) -> list[Sequence[Any]]:
    return [
        (
            entree.created_at,
            entree.utilisateur_email,
            entree.action,
            libelle_module(entree.module),
            entree.description,
            entree.objet_id,
            entree.adresse_ip,
        )
        for entree in entrees
    ]


def description_filtres(parametres: ParametresListe, filtres: FiltresHistorique) -> list[str]:
    """Recherche, filtres et tri appliqués, en clair (en-tête des exports)."""
    valeurs: dict[str, dict[str, str]] = {"action": {action.value: action.libelle for action in ActionHistorique}}
    if filtres.du is not None:
        valeurs["du"] = {filtres.du.isoformat(): formater_valeur(filtres.du)}
    if filtres.au is not None:
        valeurs["au"] = {filtres.au.isoformat(): formater_valeur(filtres.au)}
    if filtres.module:
        valeurs["module"] = {filtres.module: libelle_module(filtres.module)}
    return decrire_filtres(
        parametres, libelles_filtres=LIBELLES_FILTRES, libelles_tri=LIBELLES_TRI, valeurs_filtres=valeurs
    )


async def donnees_export(request: Request, db: AsyncSession) -> tuple[list[Sequence[Any]], list[str]]:
    """TOUTES les lignes correspondant aux filtres et au tri actifs + description des filtres."""
    parametres, filtres, _ = lire_parametres(request)
    entrees = await tout_recuperer(db, requete_historique(parametres, filtres))
    return lignes_export(entrees), description_filtres(parametres, filtres)
