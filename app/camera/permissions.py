"""Permissions du module caméra.

- ADMIN : configuration des caméras, modification des noms/emplacements, consultation et exports.
- MANAGER : consultation de la liste des caméras, des passages et exports (lecture seule).
- UTILISATEUR : aucun accès à ce module.
"""

from typing import Annotated

from fastapi import Depends

from app.core.dependencies import exiger_roles
from app.utilisateur.model import Role, User

ROLES_LECTURE = (Role.ADMIN, Role.MANAGER)
ROLES_GESTION = (Role.ADMIN,)

peut_lire = exiger_roles(*ROLES_LECTURE)
peut_gerer = exiger_roles(*ROLES_GESTION)

LecteurCameras = Annotated[User, Depends(peut_lire)]
GestionnaireCameras = Annotated[User, Depends(peut_gerer)]


def peut_gerer_cameras(utilisateur: User | None) -> bool:
    """Vrai si l'utilisateur peut modifier les paramètres des caméras."""
    return utilisateur is not None and utilisateur.role in ROLES_GESTION
