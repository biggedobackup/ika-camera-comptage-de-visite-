"""Services du module auth : connexion (verrouillage, étape OTP), ouverture et fermeture de session,
inscription, mot de passe oublié / réinitialisation, profil et double authentification.

Toutes les actions sont journalisées via `app.historique.services.journaliser` (module « auth »).
Le hachage bcrypt (coûteux) est exécuté dans un thread pour ne pas bloquer la boucle asynchrone.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.auth import otp
from app.auth.model import JetonReinitialisation
from app.auth.schemas import SchemaInscription, SchemaProfil
from app.core.config import settings
from app.core.database import maintenant
from app.core.mail import envoyer_email
from app.core.security import (
    DUREE_VERROUILLAGE_MINUTES,
    MAX_TENTATIVES_CONNEXION,
    MOT_DE_PASSE_LONGUEUR_MAX,
    NOM_COOKIE_JETON,
    JetonAcces,
    chiffrer_secret,
    creer_jeton_acces,
    dechiffrer_secret,
    decoder_jeton_acces,
    generer_jeton,
    hacher_jeton,
    hacher_mot_de_passe,
    regenerer_session,
    reinitialiser_limite_connexion,
    revoquer_jeton,
    url_redirection_sure,
    verifier_mot_de_passe,
    verifier_mot_de_passe_factice,
)
from app.historique.model import ActionHistorique
from app.historique.services import instantane, journaliser
from app.utilisateur.model import Role, User

logger = logging.getLogger("app.auth")

MODULE = "auth"

# Colonnes photographiées dans l'historique (jamais de hash ni de secret).
CHAMPS_JOURNAL_UTILISATEUR = ["nom_complet", "email", "telephone", "role", "est_actif"]
CHAMPS_PROFIL = ["nom_complet", "telephone"]

# ---------------------------------------------------------------------------
# Messages affichés à l'utilisateur
# ---------------------------------------------------------------------------

MESSAGE_IDENTIFIANTS_INVALIDES = (
    "Adresse e-mail ou mot de passe incorrect. Vérifiez vos identifiants puis réessayez. "
    f"Après {MAX_TENTATIVES_CONNEXION} échecs consécutifs, le compte est verrouillé pendant "
    f"{DUREE_VERROUILLAGE_MINUTES} minutes."
)
MESSAGE_COMPTE_DESACTIVE = (
    "Votre compte est désactivé : vous ne pouvez pas vous connecter. Contactez un administrateur."
)
MESSAGE_CODE_OTP_INVALIDE = (
    "Code de vérification incorrect ou expiré. Saisissez le code actuellement affiché dans votre "
    "application d'authentification (vérifiez que l'heure de votre téléphone est exacte)."
)
MESSAGE_OTP_EXPIRE = (
    "Votre étape de vérification a expiré ou n'est plus valide. "
    "Saisissez à nouveau votre adresse e-mail et votre mot de passe."
)
MESSAGE_OTP_INUTILISABLE = (
    "La double authentification de ce compte ne peut pas être vérifiée (configuration illisible). "
    "Contactez un administrateur."
)
MESSAGE_CONNEXION_REUSSIE = "Connexion réussie. Bienvenue, {nom} !"
MESSAGE_DECONNEXION = "Vous avez été déconnecté avec succès. À bientôt !"
MESSAGE_INSCRIPTION_REUSSIE = (
    "Votre compte a été créé avec succès. Vous pouvez maintenant vous connecter avec votre adresse "
    "e-mail et votre mot de passe."
)
MESSAGE_EMAIL_DEJA_UTILISE = "Un compte existe déjà avec cette adresse e-mail. Connectez-vous ou utilisez une autre adresse."
MESSAGE_DEMANDE_REINITIALISATION = (
    "Si un compte actif est associé à l'adresse {email}, un e-mail contenant un lien de "
    "réinitialisation vient d'y être envoyé. Ce lien est valable {minutes} minutes et ne peut être "
    "utilisé qu'une seule fois. Pensez à vérifier vos courriers indésirables."
)
MESSAGE_REINITIALISATION_REUSSIE = (
    "Votre mot de passe a été réinitialisé avec succès. "
    "Vous pouvez maintenant vous connecter avec votre nouveau mot de passe."
)
MESSAGE_JETON_INCONNU = (
    "Ce lien de réinitialisation est invalide. Vérifiez que vous avez utilisé le lien complet reçu "
    "par e-mail (seul le dernier lien demandé est valable), ou faites une nouvelle demande."
)
MESSAGE_JETON_UTILISE = (
    "Ce lien de réinitialisation a déjà été utilisé. Si nécessaire, faites une nouvelle demande."
)
MESSAGE_JETON_EXPIRE = (
    "Ce lien de réinitialisation a expiré (il est valable {minutes} minutes). "
    "Faites une nouvelle demande de réinitialisation."
)
MESSAGE_JETON_COMPTE_DESACTIVE = (
    "Ce compte est désactivé : son mot de passe ne peut pas être réinitialisé. Contactez un administrateur."
)
MESSAGE_PROFIL_MODIFIE = "Vos informations ont été mises à jour avec succès."
MESSAGE_PROFIL_INCHANGE = "Aucune modification n'a été apportée à vos informations."
MESSAGE_MOT_DE_PASSE_ACTUEL_INCORRECT = "Le mot de passe actuel est incorrect."
MESSAGE_MOT_DE_PASSE_MODIFIE = "Votre mot de passe a été modifié avec succès."
MESSAGE_OTP_ACTIVEE = (
    "La double authentification est activée. Un code à 6 chiffres vous sera demandé à chaque connexion."
)
MESSAGE_OTP_DEJA_ACTIVEE = "La double authentification est déjà activée sur votre compte."
MESSAGE_OTP_DESACTIVEE = (
    "La double authentification a été désactivée. Votre compte est désormais protégé uniquement "
    "par votre mot de passe."
)
MESSAGE_OTP_DEJA_DESACTIVEE = "La double authentification n'est pas activée sur votre compte."


def message_verrouillage(minutes: int) -> str:
    """Message de compte verrouillé avec la durée restante."""
    pluriel = "s" if minutes > 1 else ""
    return (
        f"Votre compte est temporairement verrouillé après {MAX_TENTATIVES_CONNEXION} tentatives de "
        f"connexion échouées. Réessayez dans {minutes} minute{pluriel}, ou réinitialisez votre mot "
        "de passe avec le lien « Mot de passe oublié ? »."
    )


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------


def normaliser_email(email: str) -> str:
    """E-mail comparé et stocké en minuscules, sans espaces autour."""
    return email.strip().lower()


async def trouver_utilisateur_par_email(
    db: AsyncSession, email: str, *, verrouiller: bool = False
) -> User | None:
    """Utilisateur par e-mail. `verrouiller=True` pose un verrou de ligne (SELECT … FOR UPDATE)."""
    requete = select(User).where(User.email == normaliser_email(email))
    if verrouiller:
        requete = requete.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(requete)


async def _mot_de_passe_valide(mot_de_passe: str, mot_de_passe_hash: str) -> bool:
    """Vérification bcrypt hors de la boucle asynchrone (temps constant, même si trop long)."""
    if len(mot_de_passe.encode("utf-8")) > MOT_DE_PASSE_LONGUEUR_MAX:
        await run_in_threadpool(verifier_mot_de_passe_factice)
        return False
    return await run_in_threadpool(verifier_mot_de_passe, mot_de_passe, mot_de_passe_hash)


async def _hacher(mot_de_passe: str) -> str:
    return await run_in_threadpool(hacher_mot_de_passe, mot_de_passe)


def _lever_verrouillage_expire(utilisateur: User) -> None:
    """Verrouillage terminé : le compteur d'échecs repart de zéro."""
    if utilisateur.verrouille_jusqua is not None and not utilisateur.est_verrouille:
        utilisateur.verrouille_jusqua = None
        utilisateur.tentatives_echouees = 0


def _reinitialiser_compteurs(utilisateur: User) -> None:
    """Remise à zéro après une authentification réussie (ou une réinitialisation du mot de passe)."""
    if utilisateur.tentatives_echouees:
        utilisateur.tentatives_echouees = 0
    if utilisateur.verrouille_jusqua is not None:
        utilisateur.verrouille_jusqua = None


# ---------------------------------------------------------------------------
# Connexion
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResultatAuthentification:
    """Résultat d'une étape d'authentification.

    `abandonner` : l'étape OTP doit être abandonnée (retour à l'écran de connexion).
    """

    utilisateur: User | None = None
    erreur: str | None = None
    abandonner: bool = False


async def _enregistrer_echec(
    db: AsyncSession, request: Request, utilisateur: User, motif: str, message_echec: str
) -> tuple[str, bool]:
    """Incrémente le compteur d'échecs, verrouille au-delà du seuil, journalise et valide.

    Retourne (message à afficher, compte_verrouillé).
    """
    utilisateur.tentatives_echouees += 1
    tentatives = utilisateur.tentatives_echouees
    verrouille = tentatives >= MAX_TENTATIVES_CONNEXION
    await journaliser(
        db,
        action=ActionHistorique.ECHEC_CONNEXION,
        module=MODULE,
        description=(
            f"Échec de connexion de {utilisateur.email} : {motif} "
            f"(échec {tentatives} sur {MAX_TENTATIVES_CONNEXION} avant verrouillage)."
        ),
        utilisateur=utilisateur,
        objet_id=utilisateur.id,
        request=request,
    )
    if verrouille:
        utilisateur.verrouille_jusqua = maintenant() + timedelta(minutes=DUREE_VERROUILLAGE_MINUTES)
        await journaliser(
            db,
            action=ActionHistorique.VERROUILLAGE,
            module=MODULE,
            description=(
                f"Compte {utilisateur.email} verrouillé pendant {DUREE_VERROUILLAGE_MINUTES} minutes "
                f"après {MAX_TENTATIVES_CONNEXION} échecs de connexion consécutifs."
            ),
            utilisateur=utilisateur,
            objet_id=utilisateur.id,
            donnees_apres={"verrouille_jusqua": utilisateur.verrouille_jusqua},
            request=request,
        )
    await db.commit()
    if verrouille:
        return message_verrouillage(DUREE_VERROUILLAGE_MINUTES), True
    return message_echec, False


async def _refuser(
    db: AsyncSession, request: Request, utilisateur: User, description: str
) -> None:
    """Journalise une tentative de connexion refusée (compte verrouillé ou désactivé) et valide."""
    await journaliser(
        db,
        action=ActionHistorique.ECHEC_CONNEXION,
        module=MODULE,
        description=description,
        utilisateur=utilisateur,
        objet_id=utilisateur.id,
        request=request,
    )
    await db.commit()


async def authentifier(
    db: AsyncSession, request: Request, email: str, mot_de_passe: str
) -> ResultatAuthentification:
    """Vérifie e-mail + mot de passe, en appliquant verrouillage et journalisation.

    Ordre : compte inconnu → compte verrouillé → mot de passe → compte désactivé (révélé
    uniquement après un mot de passe correct). Succès : compteurs remis à zéro (validé).
    """
    email = normaliser_email(email)
    utilisateur = await trouver_utilisateur_par_email(db, email, verrouiller=True)

    if utilisateur is None:
        await run_in_threadpool(verifier_mot_de_passe_factice)  # anti-énumération par le temps
        await journaliser(
            db,
            action=ActionHistorique.ECHEC_CONNEXION,
            module=MODULE,
            description=f"Échec de connexion : aucun compte n'existe pour l'adresse {email}.",
            utilisateur_email=email,
            request=request,
        )
        await db.commit()
        return ResultatAuthentification(erreur=MESSAGE_IDENTIFIANTS_INVALIDES)

    _lever_verrouillage_expire(utilisateur)
    if utilisateur.est_verrouille:
        minutes = utilisateur.minutes_verrouillage_restantes
        await _refuser(
            db, request, utilisateur,
            f"Connexion refusée pour {email} : compte verrouillé (encore {minutes} min).",
        )
        return ResultatAuthentification(erreur=message_verrouillage(minutes))

    if not await _mot_de_passe_valide(mot_de_passe, utilisateur.mot_de_passe_hash):
        message, _ = await _enregistrer_echec(
            db, request, utilisateur, "mot de passe incorrect", MESSAGE_IDENTIFIANTS_INVALIDES
        )
        return ResultatAuthentification(erreur=message)

    if not utilisateur.est_actif:
        await _refuser(db, request, utilisateur, f"Connexion refusée pour {email} : compte désactivé.")
        return ResultatAuthentification(erreur=MESSAGE_COMPTE_DESACTIVE)

    _reinitialiser_compteurs(utilisateur)
    await db.commit()
    return ResultatAuthentification(utilisateur=utilisateur)


# --- Étape OTP en attente (stockée dans la session signée) ------------------

CLE_SESSION_OTP_EN_ATTENTE = "otp_en_attente"
DUREE_OTP_EN_ATTENTE_SECONDES = 5 * 60


@dataclass(frozen=True, slots=True)
class OtpEnAttente:
    utilisateur_id: uuid.UUID
    suivant: str


def mettre_otp_en_attente(request: Request, utilisateur: User, suivant: str) -> None:
    """Mot de passe vérifié : mémorise l'utilisateur en attente du code OTP (5 minutes)."""
    request.session[CLE_SESSION_OTP_EN_ATTENTE] = {
        "utilisateur_id": str(utilisateur.id),
        "expire_le": int(time.time()) + DUREE_OTP_EN_ATTENTE_SECONDES,
        "suivant": suivant,
    }


def lire_otp_en_attente(request: Request) -> OtpEnAttente | None:
    """Étape OTP en cours, ou None si absente, invalide ou expirée (elle est alors effacée)."""
    donnees = request.session.get(CLE_SESSION_OTP_EN_ATTENTE)
    if donnees is None:
        return None
    try:
        expire_le = int(donnees["expire_le"])
        utilisateur_id = uuid.UUID(str(donnees["utilisateur_id"]))
        suivant = url_redirection_sure(str(donnees.get("suivant") or ""), "")
    except (KeyError, TypeError, ValueError, AttributeError):
        expire_le, utilisateur_id, suivant = 0, None, ""
    if utilisateur_id is None or expire_le < time.time():
        annuler_otp_en_attente(request)
        return None
    return OtpEnAttente(utilisateur_id=utilisateur_id, suivant=suivant)


def annuler_otp_en_attente(request: Request) -> None:
    request.session.pop(CLE_SESSION_OTP_EN_ATTENTE, None)


def _secret_otp(utilisateur: User) -> str | None:
    """Secret TOTP déchiffré, ou None s'il est absent ou illisible (SECRET_KEY modifiée…)."""
    if not utilisateur.otp_secret_chiffre:
        return None
    try:
        return dechiffrer_secret(utilisateur.otp_secret_chiffre)
    except ValueError:
        logger.error("Secret OTP illisible pour l'utilisateur %s.", utilisateur.id)
        return None


async def verifier_otp_connexion(
    db: AsyncSession, request: Request, utilisateur_id: uuid.UUID, code: str
) -> ResultatAuthentification:
    """Deuxième étape de connexion : vérifie le code TOTP (un code faux compte comme un échec)."""
    utilisateur = await db.get(User, utilisateur_id, with_for_update=True, populate_existing=True)
    if utilisateur is None or not utilisateur.otp_active:
        return ResultatAuthentification(erreur=MESSAGE_OTP_EXPIRE, abandonner=True)

    _lever_verrouillage_expire(utilisateur)
    if utilisateur.est_verrouille:
        minutes = utilisateur.minutes_verrouillage_restantes
        await _refuser(
            db, request, utilisateur,
            f"Vérification OTP refusée pour {utilisateur.email} : compte verrouillé (encore {minutes} min).",
        )
        return ResultatAuthentification(erreur=message_verrouillage(minutes), abandonner=True)

    if not utilisateur.est_actif:
        await _refuser(
            db, request, utilisateur, f"Vérification OTP refusée pour {utilisateur.email} : compte désactivé."
        )
        return ResultatAuthentification(erreur=MESSAGE_COMPTE_DESACTIVE, abandonner=True)

    secret = _secret_otp(utilisateur)
    if secret is None:
        await _refuser(
            db, request, utilisateur,
            f"Vérification OTP impossible pour {utilisateur.email} : secret absent ou illisible.",
        )
        return ResultatAuthentification(erreur=MESSAGE_OTP_INUTILISABLE, abandonner=True)

    if not otp.verifier_code(secret, code):
        message, verrouille = await _enregistrer_echec(
            db, request, utilisateur, "code de vérification OTP incorrect", MESSAGE_CODE_OTP_INVALIDE
        )
        return ResultatAuthentification(erreur=message, abandonner=verrouille)

    _reinitialiser_compteurs(utilisateur)
    await db.commit()
    return ResultatAuthentification(utilisateur=utilisateur)


# ---------------------------------------------------------------------------
# Ouverture et fermeture de session
# ---------------------------------------------------------------------------


def _expiration(revendications: dict[str, Any]) -> datetime:
    return datetime.fromtimestamp(int(revendications["exp"]), UTC)


async def ouvrir_session(
    db: AsyncSession, request: Request, utilisateur: User, *, double_authentification: bool = False
) -> JetonAcces:
    """Connexion réussie : révoque l'éventuel ancien JWT, régénère la session (nouveau CSRF),
    émet un nouveau JWT (nouveau jti), met à jour la dernière connexion et journalise.

    L'appelant pose le cookie avec `definir_cookie_jeton(response, jeton)`, puis appelle flash().
    """
    ancien = request.cookies.get(NOM_COOKIE_JETON)
    revendications = decoder_jeton_acces(ancien) if ancien else None
    if revendications is not None:
        await revoquer_jeton(db, revendications["jti"], _expiration(revendications))

    regenerer_session(request)
    jeton = creer_jeton_acces(utilisateur.id)
    utilisateur.derniere_connexion = maintenant()
    mode = " avec double authentification" if double_authentification else ""
    await journaliser(
        db,
        action=ActionHistorique.CONNEXION,
        module=MODULE,
        description=f"Connexion réussie de {utilisateur.email}{mode}.",
        utilisateur=utilisateur,
        objet_id=utilisateur.id,
        request=request,
    )
    await db.commit()
    reinitialiser_limite_connexion(utilisateur.email)
    return jeton


async def fermer_session(db: AsyncSession, request: Request, utilisateur: User) -> None:
    """Déconnexion : ajoute le jti courant à la liste de révocation, journalise et vide la session."""
    revendications: dict[str, Any] = request.state.jeton
    await revoquer_jeton(db, revendications["jti"], _expiration(revendications))
    await journaliser(
        db,
        action=ActionHistorique.DECONNEXION,
        module=MODULE,
        description=f"Déconnexion de {utilisateur.email}.",
        utilisateur=utilisateur,
        objet_id=utilisateur.id,
        request=request,
    )
    await db.commit()
    request.session.clear()


# ---------------------------------------------------------------------------
# Inscription
# ---------------------------------------------------------------------------


class EmailDejaUtilise(Exception):
    """Un compte existe déjà avec cette adresse e-mail."""


async def email_existe(db: AsyncSession, email: str) -> bool:
    return await db.scalar(select(User.id).where(User.email == normaliser_email(email))) is not None


async def inscrire(db: AsyncSession, request: Request, donnees: SchemaInscription) -> User:
    """Crée un compte actif de rôle UTILISATEUR. Lève EmailDejaUtilise si l'e-mail est pris."""
    email = normaliser_email(donnees.email)
    if await email_existe(db, email):
        raise EmailDejaUtilise
    utilisateur = User(
        nom_complet=donnees.nom_complet,
        email=email,
        telephone=donnees.telephone,
        mot_de_passe_hash=await _hacher(donnees.mot_de_passe),
        role=Role.UTILISATEUR,
        est_actif=True,
    )
    db.add(utilisateur)
    try:
        await db.flush()
    except IntegrityError as exc:  # inscription simultanée avec le même e-mail
        await db.rollback()
        raise EmailDejaUtilise from exc
    await journaliser(
        db,
        action=ActionHistorique.INSCRIPTION,
        module=MODULE,
        description=f"Inscription de {email} (rôle {Role.UTILISATEUR.libelle}).",
        utilisateur=utilisateur,
        objet_id=utilisateur.id,
        donnees_apres=instantane(utilisateur, CHAMPS_JOURNAL_UTILISATEUR),
        request=request,
    )
    await db.commit()
    return utilisateur


# ---------------------------------------------------------------------------
# Mot de passe oublié / réinitialisation
# ---------------------------------------------------------------------------


def lien_reinitialisation(jeton: str) -> str:
    return settings.APP_BASE_URL.rstrip("/") + "/mot-de-passe/reinitialiser?" + urlencode({"jeton": jeton})


async def demander_reinitialisation(
    db: AsyncSession, request: Request, email: str
) -> tuple[User, str] | None:
    """Crée un jeton de réinitialisation (stocké haché) pour un compte actif.

    Retourne (utilisateur, jeton en clair à envoyer) ou None si aucun compte actif ne correspond.
    Les jetons non utilisés précédents sont supprimés : seul le dernier lien est valable.
    """
    utilisateur = await trouver_utilisateur_par_email(db, email)
    if utilisateur is None or not utilisateur.est_actif:
        return None
    await db.execute(
        delete(JetonReinitialisation).where(
            JetonReinitialisation.utilisateur_id == utilisateur.id,
            JetonReinitialisation.utilise_le.is_(None),
        )
    )
    jeton = generer_jeton()
    db.add(
        JetonReinitialisation(
            utilisateur_id=utilisateur.id,
            jeton_hash=hacher_jeton(jeton),
            expire_le=maintenant() + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES),
        )
    )
    await journaliser(
        db,
        action=ActionHistorique.DEMANDE_REINITIALISATION_MOT_DE_PASSE,
        module=MODULE,
        description=f"Demande de réinitialisation du mot de passe pour {utilisateur.email}.",
        utilisateur=utilisateur,
        objet_id=utilisateur.id,
        request=request,
    )
    await db.commit()
    return utilisateur, jeton


async def envoyer_email_reinitialisation(destinataire: str, nom_complet: str, jeton: str) -> None:
    """E-mail contenant le lien de réinitialisation (exécuté en tâche de fond après la réponse)."""
    minutes = settings.PASSWORD_RESET_EXPIRE_MINUTES
    texte = (
        f"Bonjour {nom_complet},\n\n"
        f"Une réinitialisation du mot de passe de votre compte {settings.APP_NAME} a été demandée.\n"
        f"Pour choisir un nouveau mot de passe, ouvrez le lien ci-dessous "
        f"(valable {minutes} minutes, utilisable une seule fois) :\n\n"
        f"{lien_reinitialisation(jeton)}\n\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message : "
        "votre mot de passe actuel reste inchangé.\n\n"
        f"L'équipe {settings.APP_NAME}"
    )
    await envoyer_email(destinataire, f"Réinitialisation de votre mot de passe — {settings.APP_NAME}", texte)


class JetonInvalide(Exception):
    """Lien de réinitialisation inutilisable ; `message` explique pourquoi."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


async def verifier_jeton_reinitialisation(
    db: AsyncSession, jeton: str | None, *, verrouiller: bool = False
) -> tuple[JetonReinitialisation, User]:
    """Retourne (jeton, utilisateur) si le lien est utilisable, sinon lève JetonInvalide."""
    if not jeton or len(jeton) > 128:
        raise JetonInvalide(MESSAGE_JETON_INCONNU)
    requete = select(JetonReinitialisation).where(JetonReinitialisation.jeton_hash == hacher_jeton(jeton))
    if verrouiller:
        requete = requete.with_for_update().execution_options(populate_existing=True)
    enregistrement = await db.scalar(requete)
    if enregistrement is None:
        raise JetonInvalide(MESSAGE_JETON_INCONNU)
    if enregistrement.utilise_le is not None:
        raise JetonInvalide(MESSAGE_JETON_UTILISE)
    if not enregistrement.est_valide:
        raise JetonInvalide(MESSAGE_JETON_EXPIRE.format(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES))
    utilisateur = await db.get(User, enregistrement.utilisateur_id)
    if utilisateur is None:
        raise JetonInvalide(MESSAGE_JETON_INCONNU)
    if not utilisateur.est_actif:
        raise JetonInvalide(MESSAGE_JETON_COMPTE_DESACTIVE)
    return enregistrement, utilisateur


async def reinitialiser_mot_de_passe(
    db: AsyncSession,
    request: Request,
    enregistrement: JetonReinitialisation,
    utilisateur: User,
    nouveau_mot_de_passe: str,
) -> None:
    """Change le mot de passe, consomme le jeton (usage unique), invalide les autres liens,
    lève un éventuel verrouillage, journalise et valide."""
    utilisateur.mot_de_passe_hash = await _hacher(nouveau_mot_de_passe)
    enregistrement.utilise_le = maintenant()
    await db.execute(
        delete(JetonReinitialisation).where(
            JetonReinitialisation.utilisateur_id == utilisateur.id,
            JetonReinitialisation.utilise_le.is_(None),
            JetonReinitialisation.id != enregistrement.id,
        )
    )
    _reinitialiser_compteurs(utilisateur)
    await journaliser(
        db,
        action=ActionHistorique.REINITIALISATION_MOT_DE_PASSE,
        module=MODULE,
        description=f"Réinitialisation du mot de passe de {utilisateur.email} via le lien reçu par e-mail.",
        utilisateur=utilisateur,
        objet_id=utilisateur.id,
        request=request,
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Profil
# ---------------------------------------------------------------------------


async def modifier_profil(db: AsyncSession, request: Request, utilisateur: User, donnees: SchemaProfil) -> bool:
    """Met à jour nom et téléphone. Retourne False si rien n'a changé (aucune écriture)."""
    avant = instantane(utilisateur, CHAMPS_PROFIL)
    utilisateur.nom_complet = donnees.nom_complet
    utilisateur.telephone = donnees.telephone
    apres = instantane(utilisateur, CHAMPS_PROFIL)
    if apres == avant:
        return False
    await journaliser(
        db,
        action=ActionHistorique.MODIFICATION,
        module=MODULE,
        description=f"Modification de son profil par {utilisateur.email}.",
        utilisateur=utilisateur,
        objet_id=utilisateur.id,
        donnees_avant=avant,
        donnees_apres=apres,
        request=request,
    )
    await db.commit()
    return True


async def changer_mot_de_passe(
    db: AsyncSession, request: Request, utilisateur: User, mot_de_passe_actuel: str, nouveau_mot_de_passe: str
) -> bool:
    """Change le mot de passe après vérification de l'actuel. Retourne False si l'actuel est faux."""
    if not await _mot_de_passe_valide(mot_de_passe_actuel, utilisateur.mot_de_passe_hash):
        return False
    utilisateur.mot_de_passe_hash = await _hacher(nouveau_mot_de_passe)
    await journaliser(
        db,
        action=ActionHistorique.CHANGEMENT_MOT_DE_PASSE,
        module=MODULE,
        description=f"Changement de mot de passe de {utilisateur.email} depuis son profil.",
        utilisateur=utilisateur,
        objet_id=utilisateur.id,
        request=request,
    )
    await db.commit()
    return True


# ---------------------------------------------------------------------------
# Configuration de la double authentification
# ---------------------------------------------------------------------------

CLE_SESSION_OTP_CONFIGURATION = "otp_configuration"


def secret_otp_en_configuration(request: Request) -> str:
    """Secret TOTP proposé pendant la configuration (conservé chiffré dans la session, pour que le
    QR code reste le même si la page est rechargée). Il n'est enregistré qu'après un code valide."""
    chiffre = request.session.get(CLE_SESSION_OTP_CONFIGURATION)
    if isinstance(chiffre, str):
        try:
            return dechiffrer_secret(chiffre)
        except ValueError:
            pass
    secret = otp.generer_secret()
    request.session[CLE_SESSION_OTP_CONFIGURATION] = chiffrer_secret(secret)
    return secret


async def activer_otp(db: AsyncSession, request: Request, utilisateur: User, secret: str) -> None:
    """Enregistre le secret (chiffré) et active l'OTP. Le code doit avoir été vérifié avant."""
    utilisateur.otp_secret_chiffre = chiffrer_secret(secret)
    utilisateur.otp_active = True
    await journaliser(
        db,
        action=ActionHistorique.OTP_ACTIVATION,
        module=MODULE,
        description=f"Activation de la double authentification par {utilisateur.email}.",
        utilisateur=utilisateur,
        objet_id=utilisateur.id,
        donnees_avant={"otp_active": False},
        donnees_apres={"otp_active": True},
        request=request,
    )
    await db.commit()
    request.session.pop(CLE_SESSION_OTP_CONFIGURATION, None)


async def desactiver_otp(
    db: AsyncSession, request: Request, utilisateur: User, mot_de_passe_actuel: str
) -> bool:
    """Désactive l'OTP et efface le secret après vérification du mot de passe (False s'il est faux)."""
    if not await _mot_de_passe_valide(mot_de_passe_actuel, utilisateur.mot_de_passe_hash):
        return False
    utilisateur.otp_active = False
    utilisateur.otp_secret_chiffre = None
    await journaliser(
        db,
        action=ActionHistorique.OTP_DESACTIVATION,
        module=MODULE,
        description=f"Désactivation de la double authentification par {utilisateur.email}.",
        utilisateur=utilisateur,
        objet_id=utilisateur.id,
        donnees_avant={"otp_active": True},
        donnees_apres={"otp_active": False},
        request=request,
    )
    await db.commit()
    return True
