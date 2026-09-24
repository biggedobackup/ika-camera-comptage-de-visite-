"""Permissions du module utilisateur.

- ADMIN : gestion complète (création, modification, suppression, déverrouillage, réinitialisation OTP).
- MANAGER : lecture seule (liste, fiche détail) et exports PDF / Excel.
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

# Dépendances à utiliser dans les routes (403 si le rôle ne convient pas).
LecteurUtilisateurs = Annotated[User, Depends(peut_lire)]
GestionnaireUtilisateurs = Annotated[User, Depends(peut_gerer)]


def peut_gerer_utilisateurs(utilisateur: User | None) -> bool:
    """Vrai si l'utilisateur peut créer, modifier ou supprimer des comptes (affichage des boutons)."""
    return utilisateur is not None and utilisateur.role in ROLES_GESTION
