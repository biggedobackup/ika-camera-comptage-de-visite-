"""Services du module utilisateur : requêtes de liste (partagées avec les exports), CRUD journalisé
et garde-fous (e-mail unique, pas d'auto-suppression, dernier administrateur actif protégé)."""

import dataclasses
import enum
import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import Request
from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.database import maintenant
from app.core.listes import (
    ParametresListe,
    appliquer_recherche,
    appliquer_tri,
    decrire_filtres,
    lire_parametres_liste,
)
from app.core.security import hacher_mot_de_passe
from app.core.validation import CHAMP_GENERAL
from app.historique.model import ActionHistorique
from app.historique.services import instantane, journaliser
from app.utilisateur.model import Role, User
from app.utilisateur.schemas import UtilisateurCreation, UtilisateurModification

MODULE = "utilisateur"

# Colonnes photographiées dans l'historique (jamais de mot de passe, hash ni secret OTP).
CHAMPS_JOURNAL = ("nom_complet", "email", "telephone", "role", "est_actif")
LIBELLES_CHAMPS = {
    "nom_complet": "nom complet",
    "email": "e-mail",
    "telephone": "téléphone",
    "role": "rôle",
    "est_actif": "compte actif",
}

# ---------------------------------------------------------------------------
# Liste : recherche, filtres (rôle, statut) et tri en liste blanche
# ---------------------------------------------------------------------------


class Statut(enum.StrEnum):
    """Statut affiché d'un compte (filtre de la liste)."""

    ACTIF = "actif"
    INACTIF = "inactif"
    VERROUILLE = "verrouille"

    @property
    def libelle(self) -> str:
        return LIBELLES_STATUTS[self]


LIBELLES_STATUTS: dict[Statut, str] = {
    Statut.ACTIF: "Actif",
    Statut.INACTIF: "Inactif",
    Statut.VERROUILLE: "Verrouillé",
}

COLONNES_TRI: dict[str, Any] = {
    "nom_complet": User.nom_complet,
    "role": User.role,
    "est_actif": User.est_actif,
    "derniere_connexion": User.derniere_connexion,
    "created_at": User.created_at,
}
LIBELLES_TRI = {
    "nom_complet": "Nom complet",
    "role": "Rôle",
    "est_actif": "Statut",
    "derniere_connexion": "Dernière connexion",
    "created_at": "Date de création",
}
TRI_DEFAUT = "created_at"
ORDRE_DEFAUT = "desc"

VALEURS_FILTRES: dict[str, dict[str, str]] = {
    "role": {role.value: role.libelle for role in Role},
    "statut": {statut.value: statut.libelle for statut in Statut},
}
LIBELLES_FILTRES = {"role": "Rôle", "statut": "Statut"}

OPTIONS_ROLES: list[tuple[str, str]] = list(VALEURS_FILTRES["role"].items())
OPTIONS_STATUTS: list[tuple[str, str]] = list(VALEURS_FILTRES["statut"].items())


def lire_parametres(request: Request) -> ParametresListe:
    """Paramètres de la liste (et des exports) ; les valeurs de filtre hors liste blanche sont ignorées."""
    parametres = lire_parametres_liste(
        request,
        colonnes_tri=COLONNES_TRI.keys(),
        tri_defaut=TRI_DEFAUT,
        ordre_defaut=ORDRE_DEFAUT,
        filtres=VALEURS_FILTRES.keys(),
    )
    filtres = {nom: valeur for nom, valeur in parametres.filtres.items() if valeur in VALEURS_FILTRES[nom]}
    return dataclasses.replace(parametres, filtres=filtres)


def statut_compte(compte: User) -> Statut:
    """Statut affiché : inactif prime sur verrouillé."""
    if not compte.est_actif:
        return Statut.INACTIF
    if compte.est_verrouille:
        return Statut.VERROUILLE
    return Statut.ACTIF


def _condition_statut(statut: Statut) -> ColumnElement[bool]:
    instant = maintenant()
    if statut is Statut.INACTIF:
        return User.est_actif.is_(False)
    if statut is Statut.VERROUILLE:
        return and_(User.est_actif.is_(True), User.verrouille_jusqua > instant)
    return and_(
        User.est_actif.is_(True),
        or_(User.verrouille_jusqua.is_(None), User.verrouille_jusqua <= instant),
    )


def requete_utilisateurs(parametres: ParametresListe) -> Select:
    """Requête filtrée et triée, partagée par la liste paginée et les exports PDF / Excel."""
    requete = appliquer_recherche(select(User), parametres.recherche, [User.nom_complet, User.email, User.telephone])
    if role := parametres.filtres.get("role"):
        requete = requete.where(User.role == Role(role))
    if statut := parametres.filtres.get("statut"):
        requete = requete.where(_condition_statut(Statut(statut)))
    return appliquer_tri(requete, parametres, COLONNES_TRI, departage=User.id)


# ---------------------------------------------------------------------------
# Exports (colonnes communes au PDF et à l'Excel)
# ---------------------------------------------------------------------------

TITRE_EXPORT = "Liste des utilisateurs"
NOM_FICHIER_EXPORT = "utilisateurs"
ENTETES_EXPORT = (
    "Nom complet",
    "E-mail",
    "Téléphone",
    "Rôle",
    "Statut",
    "Double authentification",
    "Dernière connexion",
    "Créé le",
)
LARGEURS_PDF = (2.2, 3.0, 1.6, 1.4, 1.1, 1.5, 1.6, 1.6)


def lignes_export(comptes: Sequence[User]) -> list[tuple[Any, ...]]:
    return [
        (
            compte.nom_complet,
            compte.email,
            compte.telephone,
            compte.role,
            statut_compte(compte),
            "Activée" if compte.otp_active else "Désactivée",
            compte.derniere_connexion,
            compte.created_at,
        )
        for compte in comptes
    ]


def filtres_export(parametres: ParametresListe) -> list[str]:
    """Description lisible de la recherche, des filtres et du tri appliqués (en-tête des exports)."""
    return decrire_filtres(
        parametres,
        libelles_filtres=LIBELLES_FILTRES,
        libelles_tri=LIBELLES_TRI,
        valeurs_filtres=VALEURS_FILTRES,
    )


# ---------------------------------------------------------------------------
# Erreurs métier (messages destinés à l'utilisateur)
# ---------------------------------------------------------------------------


class ErreurUtilisateur(Exception):
    """Refus d'une opération : `message` est affiché tel quel, `champ` désigne le champ concerné."""

    champ = CHAMP_GENERAL

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EmailDejaUtilise(ErreurUtilisateur):
    champ = "email"

    def __init__(self) -> None:
        super().__init__("Cette adresse e-mail est déjà utilisée par un autre compte. Saisissez une autre adresse.")


class ActionInterdite(ErreurUtilisateur):
    """Garde-fou : auto-suppression ou retrait du dernier administrateur actif."""


def _message_dernier_admin(compte: User, action: str) -> str:
    return (
        f"Impossible de {action} {compte.nom_complet} : c'est le dernier administrateur actif. "
        "Désignez d'abord un autre administrateur actif."
    )


# ---------------------------------------------------------------------------
# Lecture et garde-fous
# ---------------------------------------------------------------------------


async def obtenir_utilisateur(db: AsyncSession, utilisateur_id: uuid.UUID) -> User | None:
    return await db.get(User, utilisateur_id)


async def email_deja_utilise(db: AsyncSession, email: str, exclure_id: uuid.UUID | None = None) -> bool:
    """Vrai si l'adresse (insensible à la casse) appartient déjà à un autre compte."""
    requete = select(User.id).where(func.lower(User.email) == email.lower())
    if exclure_id is not None:
        requete = requete.where(User.id != exclure_id)
    return await db.scalar(requete.limit(1)) is not None


async def _est_dernier_admin_actif(db: AsyncSession, compte: User) -> bool:
    """Vrai si `compte` est le seul ADMIN actif.

    Les lignes des ADMIN actifs sont verrouillées (SELECT … FOR UPDATE) jusqu'à la fin de la
    transaction : deux retraits simultanés ne peuvent pas supprimer tous les administrateurs.
    """
    if compte.role != Role.ADMIN or not compte.est_actif:
        return False
    admins = await db.scalars(
        select(User.id).where(User.role == Role.ADMIN, User.est_actif.is_(True)).with_for_update()
    )
    return not any(admin_id != compte.id for admin_id in admins.all())


# ---------------------------------------------------------------------------
# CRUD (chaque action est journalisée dans la même transaction)
# ---------------------------------------------------------------------------


async def creer_utilisateur(
    db: AsyncSession, donnees: UtilisateurCreation, *, auteur: User, request: Request
) -> User:
    if await email_deja_utilise(db, donnees.email):
        raise EmailDejaUtilise()
    compte = User(
        nom_complet=donnees.nom_complet,
        email=donnees.email,
        telephone=donnees.telephone,
        role=donnees.role,
        est_actif=donnees.est_actif,
        mot_de_passe_hash=await run_in_threadpool(hacher_mot_de_passe, donnees.mot_de_passe),
    )
    try:
        async with db.begin_nested():
            db.add(compte)
    except IntegrityError as exc:  # création simultanée avec la même adresse
        raise EmailDejaUtilise() from exc
    await journaliser(
        db,
        action=ActionHistorique.CREATION,
        module=MODULE,
        description=f"Création du compte {compte.email} (rôle : {compte.role.libelle})",
        utilisateur=auteur,
        objet_id=compte.id,
        donnees_apres=instantane(compte, CHAMPS_JOURNAL),
        request=request,
    )
    await db.commit()
    return compte


async def modifier_utilisateur(
    db: AsyncSession, compte: User, donnees: UtilisateurModification, *, auteur: User, request: Request
) -> bool:
    """Applique les modifications. Retourne False si rien n'a changé (aucune entrée d'historique)."""
    nouvelles = donnees.model_dump(include=set(CHAMPS_JOURNAL))
    modifies = [champ for champ, valeur in nouvelles.items() if getattr(compte, champ) != valeur]
    if not modifies:
        return False
    if "email" in modifies and await email_deja_utilise(db, donnees.email, exclure_id=compte.id):
        raise EmailDejaUtilise()
    retire_un_admin = donnees.role != Role.ADMIN or not donnees.est_actif
    if retire_un_admin and await _est_dernier_admin_actif(db, compte):
        action = "désactiver" if not donnees.est_actif else "retirer le rôle Administrateur à"
        raise ActionInterdite(_message_dernier_admin(compte, action))

    avant = instantane(compte, CHAMPS_JOURNAL)
    try:
        async with db.begin_nested():
            for champ in modifies:
                setattr(compte, champ, nouvelles[champ])
    except IntegrityError as exc:  # modification simultanée vers la même adresse
        await db.refresh(compte)
        raise EmailDejaUtilise() from exc
    await journaliser(
        db,
        action=ActionHistorique.MODIFICATION,
        module=MODULE,
        description=(
            f"Modification du compte {compte.email} "
            f"({', '.join(LIBELLES_CHAMPS[champ] for champ in modifies)})"
        ),
        utilisateur=auteur,
        objet_id=compte.id,
        donnees_avant=avant,
        donnees_apres=instantane(compte, CHAMPS_JOURNAL),
        request=request,
    )
    await db.commit()
    return True


async def supprimer_utilisateur(db: AsyncSession, compte: User, *, auteur: User, request: Request) -> None:
    if compte.id == auteur.id:
        raise ActionInterdite(
            "Vous ne pouvez pas supprimer votre propre compte. Demandez à un autre administrateur de le faire."
        )
    if await _est_dernier_admin_actif(db, compte):
        raise ActionInterdite(_message_dernier_admin(compte, "supprimer"))
    await journaliser(
        db,
        action=ActionHistorique.SUPPRESSION,
        module=MODULE,
        description=f"Suppression du compte {compte.email}",
        utilisateur=auteur,
        objet_id=compte.id,
        donnees_avant=instantane(compte, CHAMPS_JOURNAL),
        request=request,
    )
    await db.delete(compte)
    await db.commit()


async def deverrouiller_utilisateur(db: AsyncSession, compte: User, *, auteur: User, request: Request) -> bool:
    """Lève le verrouillage et remet le compteur d'échecs à zéro. False si le compte n'est pas verrouillé."""
    if not compte.est_verrouille:
        return False
    champs = ("tentatives_echouees", "verrouille_jusqua")
    avant = instantane(compte, champs)
    compte.tentatives_echouees = 0
    compte.verrouille_jusqua = None
    await journaliser(
        db,
        action=ActionHistorique.MODIFICATION,
        module=MODULE,
        description=f"Déverrouillage du compte {compte.email} par un administrateur",
        utilisateur=auteur,
        objet_id=compte.id,
        donnees_avant=avant,
        donnees_apres=instantane(compte, champs),
        request=request,
    )
    await db.commit()
    return True


async def reinitialiser_otp(db: AsyncSession, compte: User, *, auteur: User, request: Request) -> bool:
    """Désactive la double authentification et efface le secret. False si elle n'était pas configurée."""
    if not compte.otp_active and compte.otp_secret_chiffre is None:
        return False
    avant = {"otp_active": compte.otp_active}
    compte.otp_active = False
    compte.otp_secret_chiffre = None
    await journaliser(
        db,
        action=ActionHistorique.OTP_DESACTIVATION,
        module=MODULE,
        description=f"Réinitialisation de la double authentification du compte {compte.email} par un administrateur",
        utilisateur=auteur,
        objet_id=compte.id,
        donnees_avant=avant,
        donnees_apres={"otp_active": compte.otp_active},
        request=request,
    )
    await db.commit()
    return True
