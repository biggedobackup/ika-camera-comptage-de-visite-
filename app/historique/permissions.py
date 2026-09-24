"""Permissions du module historique (lecture seule : consultation et exports)."""

from typing import Annotated

from fastapi import Depends

from app.core.dependencies import exiger_roles
from app.utilisateur.model import Role, User

ROLES_LECTURE = (Role.ADMIN, Role.MANAGER)

# Dépendance : ADMIN ou MANAGER, sinon page 403 (et /connexion si non connecté).
peut_lire = exiger_roles(*ROLES_LECTURE)

LecteurHistorique = Annotated[User, Depends(peut_lire)]
