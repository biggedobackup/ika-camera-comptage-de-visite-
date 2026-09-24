"""Dépendances FastAPI partagées : session de base, utilisateur courant, rôles, CSRF."""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AuthentificationRequise
from app.core.security import NOM_COOKIE_JETON, decoder_jeton_acces, jeton_est_revoque, verifier_csrf
from app.utilisateur.model import Role, User

__all__ = [
    "DbSession",
    "UtilisateurCourant",
    "UtilisateurOptionnel",
    "exiger_roles",
    "get_db",
    "get_utilisateur_courant",
    "get_utilisateur_optionnel",
    "verifier_csrf",
]

MESSAGE_SESSION_EXPIREE = "Votre session a expiré ou n'est plus valide. Veuillez vous reconnecter."
MESSAGE_COMPTE_DESACTIVE = "Votre compte est désactivé. Contactez un administrateur."
MESSAGE_CONNEXION_REQUISE = "Veuillez vous connecter pour accéder à cette page."

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def _resoudre_utilisateur(request: Request, db: AsyncSession) -> tuple[User | None, str | None]:
    """Retourne (utilisateur, motif_refus). motif_refus est None si aucun jeton n'a été présenté."""
    jeton = request.cookies.get(NOM_COOKIE_JETON)
    if not jeton:
        return None, None
    revendications = decoder_jeton_acces(jeton)
    if revendications is None or await jeton_est_revoque(db, revendications["jti"]):
        return None, MESSAGE_SESSION_EXPIREE
    try:
        utilisateur_id = uuid.UUID(revendications["sub"])
    except ValueError:
        return None, MESSAGE_SESSION_EXPIREE
    utilisateur = await db.get(User, utilisateur_id)
    if utilisateur is None:
        return None, MESSAGE_SESSION_EXPIREE
    if not utilisateur.est_actif:
        return None, MESSAGE_COMPTE_DESACTIVE
    request.state.jeton = revendications
    return utilisateur, None


async def get_utilisateur_optionnel(request: Request, db: DbSession) -> User | None:
    """Utilisateur connecté ou None (pages publiques). Pose request.state.utilisateur."""
    utilisateur, _ = await _resoudre_utilisateur(request, db)
    request.state.utilisateur = utilisateur
    return utilisateur


async def get_utilisateur_courant(request: Request, db: DbSession) -> User:
    """Utilisateur connecté obligatoire : sinon redirection vers /connexion avec un message clair.

    Refuse les JWT invalides, expirés ou révoqués, ainsi que les comptes désactivés.
    Pose request.state.utilisateur et request.state.jeton (revendications : sub, jti, exp…).
    """
    utilisateur, motif = await _resoudre_utilisateur(request, db)
    request.state.utilisateur = utilisateur
    if utilisateur is None:
        raise AuthentificationRequise(motif or MESSAGE_CONNEXION_REQUISE)
    return utilisateur


UtilisateurCourant = Annotated[User, Depends(get_utilisateur_courant)]
UtilisateurOptionnel = Annotated[User | None, Depends(get_utilisateur_optionnel)]


def exiger_roles(*roles: Role) -> Callable[..., Awaitable[User]]:
    """Fabrique une dépendance qui exige l'un des rôles donnés (403 sinon).

    Exemple : `utilisateur: User = Depends(exiger_roles(Role.ADMIN, Role.MANAGER))`
    """
    autorises = frozenset(roles)

    async def dependance(utilisateur: UtilisateurCourant) -> User:
        if utilisateur.role not in autorises:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Vous n'avez pas les droits nécessaires pour accéder à cette page.",
            )
        return utilisateur

    return dependance
