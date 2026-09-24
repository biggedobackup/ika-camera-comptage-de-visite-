"""Permissions du module auth.

- Pages publiques (connexion, inscription, mot de passe oublié, réinitialisation, vérification OTP) :
  réservées aux visiteurs non connectés ; un utilisateur déjà connecté est redirigé vers le tableau de bord.
- Pages du compte (profil, changement de mot de passe, configuration OTP) : tout utilisateur connecté,
  quel que soit son rôle (dépendance `UtilisateurCourant`).
- Déconnexion : accessible à tous ; sans session valide, elle se contente d'effacer les cookies.
"""

from fastapi.responses import RedirectResponse

from app.utilisateur.model import User

PAGE_ACCUEIL_CONNECTE = "/tableau-de-bord"


def rediriger_si_connecte(utilisateur: User | None) -> RedirectResponse | None:
    """Redirection vers le tableau de bord si l'utilisateur est déjà connecté (pages publiques)."""
    if utilisateur is None:
        return None
    return RedirectResponse(PAGE_ACCUEIL_CONNECTE, status_code=303)
