"""Création du premier administrateur (script idempotent).

Lit FIRST_ADMIN_EMAIL, FIRST_ADMIN_PASSWORD et FIRST_ADMIN_NAME (fichier .env ou variables
d'environnement), vérifie la politique de mot de passe, puis crée un compte ADMIN actif.
La création est journalisée dans l'historique.

Le script ne modifie jamais un compte existant. Rien n'est créé si :
- un compte utilise déjà l'adresse FIRST_ADMIN_EMAIL ;
- un administrateur existe déjà.

Usage (depuis la racine du projet, après « alembic upgrade head ») :
    python scripts/creer_premier_admin.py
Codes de sortie : 0 = compte créé ou déjà présent ; 1 = configuration ou base de données à corriger.
"""

import asyncio
import sys
from pathlib import Path

RACINE_PROJET = Path(__file__).resolve().parents[1]
if str(RACINE_PROJET) not in sys.path:
    sys.path.insert(0, str(RACINE_PROJET))

from pydantic import BaseModel  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError  # noqa: E402

from app.auth.schemas import Email, NomComplet  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.security import MotDePasse, hacher_mot_de_passe  # noqa: E402
from app.core.validation import valider  # noqa: E402
from app.historique.model import ActionHistorique  # noqa: E402
from app.historique.services import instantane, journaliser  # noqa: E402
from app.utilisateur.model import Role, User  # noqa: E402
from app.utilisateur.services import CHAMPS_JOURNAL  # noqa: E402

MODULE = "utilisateur"
VARIABLES = {
    "email": "FIRST_ADMIN_EMAIL",
    "nom_complet": "FIRST_ADMIN_NAME",
    "mot_de_passe": "FIRST_ADMIN_PASSWORD",
}


class PremierAdministrateur(BaseModel):
    """Valeurs lues dans la configuration (mêmes règles que les formulaires de l'application)."""

    email: Email
    nom_complet: NomComplet
    mot_de_passe: MotDePasse


def _erreur(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


async def creer_premier_admin() -> int:
    """Crée le premier administrateur si nécessaire. Retourne le code de sortie."""
    donnees, erreurs = valider(
        PremierAdministrateur,
        {
            "email": settings.FIRST_ADMIN_EMAIL,
            "nom_complet": settings.FIRST_ADMIN_NAME,
            "mot_de_passe": settings.FIRST_ADMIN_PASSWORD,
        },
    )
    if donnees is None:
        lignes = [f"  - {VARIABLES.get(champ, champ)} : {message}" for champ, message in erreurs.items()]
        return _erreur("Configuration invalide dans le fichier .env, aucun compte créé :\n" + "\n".join(lignes))

    async with SessionLocal() as db:
        existant = await db.scalar(select(User).where(func.lower(User.email) == donnees.email))
        if existant is not None:
            if existant.role == Role.ADMIN:
                print(f"L'administrateur {existant.email} existe déjà : aucune modification.")
                return 0
            return _erreur(
                f"Le compte {existant.email} existe déjà avec le rôle « {existant.role.libelle} » : il n'a pas "
                "été modifié. Indiquez une autre adresse dans FIRST_ADMIN_EMAIL, ou attribuez-lui le rôle "
                "Administrateur depuis l'application."
            )

        admin_existant = await db.scalar(select(User.email).where(User.role == Role.ADMIN).limit(1))
        if admin_existant is not None:
            print(f"Un administrateur existe déjà ({admin_existant}) : aucun compte créé.")
            return 0

        compte = User(
            nom_complet=donnees.nom_complet,
            email=donnees.email,
            telephone=None,
            mot_de_passe_hash=hacher_mot_de_passe(donnees.mot_de_passe),
            role=Role.ADMIN,
            est_actif=True,
        )
        db.add(compte)
        try:
            await db.flush()
        except IntegrityError:  # création simultanée avec la même adresse
            print(f"L'administrateur {donnees.email} existe déjà : aucune modification.")
            return 0
        await journaliser(
            db,
            action=ActionHistorique.CREATION,
            module=MODULE,
            description=(
                f"Création du premier administrateur {compte.email} "
                "(script scripts/creer_premier_admin.py)"
            ),
            objet_id=compte.id,
            donnees_apres=instantane(compte, CHAMPS_JOURNAL),
        )
        await db.commit()

    print(f"Administrateur créé : {compte.nom_complet} <{compte.email}>.")
    print("Connectez-vous sur /connexion, puis changez ce mot de passe initial depuis la page « Mon profil ».")
    return 0


async def principal() -> int:
    try:
        return await creer_premier_admin()
    except ProgrammingError:
        return _erreur(
            "Les tables sont absentes de la base de données : appliquez d'abord les migrations "
            "avec « alembic upgrade head »."
        )
    except (OperationalError, OSError) as exc:
        return _erreur(
            "Base de données injoignable : vérifiez DATABASE_URL dans le fichier .env et que PostgreSQL "
            f"est démarré ({exc.__class__.__name__})."
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(principal()))
