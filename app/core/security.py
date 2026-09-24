"""Sécurité : mots de passe (bcrypt + politique), JWT (jti + liste de révocation), CSRF,
chiffrement des secrets OTP (Fernet), limitation de débit en mémoire et utilitaires associés."""

import base64
import hashlib
import hmac
import math
import secrets
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Annotated, Any

import bcrypt
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import HTTPException, Request, Response, status
from jose import JWTError, jwt
from pydantic import AfterValidator
from pydantic_core import PydanticCustomError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.model import JetonRevoque
from app.core.config import settings
from app.core.database import maintenant

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

ALGORITHME_JWT = "HS256"
NOM_COOKIE_JETON = "ika_jeton"
NOM_COOKIE_SESSION = "ika_session"

MAX_TENTATIVES_CONNEXION = 5
DUREE_VERROUILLAGE_MINUTES = 15

MOT_DE_PASSE_LONGUEUR_MIN = 10
MOT_DE_PASSE_LONGUEUR_MAX = 72  # limite de bcrypt (en octets)

CLE_SESSION_CSRF = "csrf_token"
NOM_CHAMP_CSRF = "csrf_token"
EN_TETE_CSRF = "X-CSRF-Token"
METHODES_SURES = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# ---------------------------------------------------------------------------
# Mots de passe
# ---------------------------------------------------------------------------

REGLES_MOT_DE_PASSE: tuple[str, ...] = (
    f"Entre {MOT_DE_PASSE_LONGUEUR_MIN} et {MOT_DE_PASSE_LONGUEUR_MAX} caractères",
    "Au moins une lettre majuscule",
    "Au moins une lettre minuscule",
    "Au moins un chiffre",
    "Au moins un caractère spécial (par exemple ! @ # ? % * -)",
)


def erreurs_politique_mot_de_passe(mot_de_passe: str) -> list[str]:
    """Retourne la liste des règles non respectées (liste vide si le mot de passe est conforme)."""
    erreurs: list[str] = []
    if len(mot_de_passe) < MOT_DE_PASSE_LONGUEUR_MIN:
        erreurs.append(f"Le mot de passe doit contenir au moins {MOT_DE_PASSE_LONGUEUR_MIN} caractères.")
    if len(mot_de_passe) > MOT_DE_PASSE_LONGUEUR_MAX:
        erreurs.append(f"Le mot de passe doit contenir au plus {MOT_DE_PASSE_LONGUEUR_MAX} caractères.")
    elif len(mot_de_passe.encode("utf-8")) > MOT_DE_PASSE_LONGUEUR_MAX:
        erreurs.append(
            "Le mot de passe est trop long : 72 octets maximum "
            "(les caractères accentués comptent pour deux)."
        )
    if not any(c.isupper() for c in mot_de_passe):
        erreurs.append("Le mot de passe doit contenir au moins une lettre majuscule.")
    if not any(c.islower() for c in mot_de_passe):
        erreurs.append("Le mot de passe doit contenir au moins une lettre minuscule.")
    if not any(c.isdigit() for c in mot_de_passe):
        erreurs.append("Le mot de passe doit contenir au moins un chiffre.")
    if not any(not c.isalnum() and not c.isspace() for c in mot_de_passe):
        erreurs.append("Le mot de passe doit contenir au moins un caractère spécial.")
    return erreurs


def valider_mot_de_passe(mot_de_passe: str) -> str:
    """Validateur Pydantic : lève une erreur lisible si la politique n'est pas respectée."""
    erreurs = erreurs_politique_mot_de_passe(mot_de_passe)
    if erreurs:
        raise PydanticCustomError("politique_mot_de_passe", " ".join(erreurs))
    return mot_de_passe


# Type à utiliser dans les schémas Pydantic : `mot_de_passe: MotDePasse`
MotDePasse = Annotated[str, AfterValidator(valider_mot_de_passe)]


def hacher_mot_de_passe(mot_de_passe: str) -> str:
    """Hache un mot de passe avec bcrypt (sel aléatoire, coût 12)."""
    return bcrypt.hashpw(mot_de_passe.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verifier_mot_de_passe(mot_de_passe: str, mot_de_passe_hash: str) -> bool:
    """Vérifie un mot de passe contre son hash bcrypt (False si invalide ou trop long)."""
    donnees = mot_de_passe.encode("utf-8")
    if len(donnees) > MOT_DE_PASSE_LONGUEUR_MAX:
        return False
    try:
        return bcrypt.checkpw(donnees, mot_de_passe_hash.encode("ascii"))
    except ValueError:
        return False


@lru_cache
def _hash_factice() -> bytes:
    return bcrypt.hashpw(secrets.token_bytes(16), bcrypt.gensalt(rounds=12))


def verifier_mot_de_passe_factice() -> None:
    """Consomme le même temps qu'une vérification réelle (e-mail inconnu : anti-énumération par timing)."""
    bcrypt.checkpw(b"mot-de-passe-factice", _hash_factice())


# ---------------------------------------------------------------------------
# Jetons aléatoires (réinitialisation de mot de passe, etc.)
# ---------------------------------------------------------------------------


def generer_jeton() -> str:
    """Jeton aléatoire sûr, utilisable dans une URL (256 bits)."""
    return secrets.token_urlsafe(32)


def hacher_jeton(jeton: str) -> str:
    """Empreinte SHA-256 hexadécimale d'un jeton (stockage en base)."""
    return hashlib.sha256(jeton.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# JWT (cookie HttpOnly) + liste de révocation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class JetonAcces:
    jeton: str
    jti: str
    expire_le: datetime


def creer_jeton_acces(utilisateur_id: uuid.UUID | str) -> JetonAcces:
    """Crée un JWT signé (HS256) avec un jti unique et une expiration ACCESS_TOKEN_EXPIRE_MINUTES."""
    emis_le = maintenant()
    expire_le = emis_le + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    jti = uuid.uuid4().hex
    revendications = {
        "sub": str(utilisateur_id),
        "jti": jti,
        "type": "acces",
        "iat": int(emis_le.timestamp()),
        "exp": int(expire_le.timestamp()),
    }
    jeton = jwt.encode(revendications, settings.SECRET_KEY, algorithm=ALGORITHME_JWT)
    return JetonAcces(jeton=jeton, jti=jti, expire_le=expire_le)


def decoder_jeton_acces(jeton: str) -> dict[str, Any] | None:
    """Décode et vérifie un JWT (signature, expiration, type). None si invalide."""
    try:
        revendications = jwt.decode(
            jeton,
            settings.SECRET_KEY,
            algorithms=[ALGORITHME_JWT],
            options={"require_exp": True, "require_sub": True, "require_jti": True},
        )
    except JWTError:
        return None
    if revendications.get("type") != "acces":
        return None
    return revendications


def definir_cookie_jeton(response: Response, jeton: JetonAcces) -> None:
    """Pose le JWT dans un cookie HttpOnly + SameSite=Lax (+ Secure selon COOKIE_SECURE)."""
    response.set_cookie(
        key=NOM_COOKIE_JETON,
        value=jeton.jeton,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


def supprimer_cookie_jeton(response: Response) -> None:
    """Supprime le cookie JWT (mêmes attributs que lors de sa création)."""
    response.delete_cookie(
        key=NOM_COOKIE_JETON,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


async def revoquer_jeton(db: AsyncSession, jti: str, expire_le: datetime) -> None:
    """Ajoute un jti à la liste de révocation et purge les entrées expirées. Ne valide pas (commit)."""
    await db.execute(delete(JetonRevoque).where(JetonRevoque.expire_le < maintenant()))
    if await db.get(JetonRevoque, jti) is None:
        db.add(JetonRevoque(jti=jti, expire_le=expire_le))
    await db.flush()


async def jeton_est_revoque(db: AsyncSession, jti: str) -> bool:
    """Vrai si le jti figure dans la liste de révocation."""
    resultat = await db.execute(select(JetonRevoque.jti).where(JetonRevoque.jti == jti))
    return resultat.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Session et CSRF
# ---------------------------------------------------------------------------


class CSRFInvalide(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Le jeton de sécurité du formulaire est absent, invalide ou expiré. "
                "Rechargez la page puis soumettez à nouveau le formulaire "
                "(les cookies doivent être autorisés pour ce site)."
            ),
        )


def obtenir_jeton_csrf(request: Request) -> str:
    """Retourne le jeton CSRF de la session (le crée si nécessaire)."""
    if "session" not in request.scope:
        return ""
    jeton = request.session.get(CLE_SESSION_CSRF)
    if not jeton:
        jeton = secrets.token_urlsafe(32)
        request.session[CLE_SESSION_CSRF] = jeton
    return jeton


async def verifier_csrf(request: Request) -> None:
    """Dépendance FastAPI : refuse (403) toute requête non sûre sans jeton CSRF valide.

    Appliquée automatiquement à tous les routers inclus dans app/main.py.
    Le jeton est lu dans le champ de formulaire « csrf_token » ou l'en-tête « X-CSRF-Token ».
    """
    if request.method in METHODES_SURES:
        return
    attendu = request.session.get(CLE_SESSION_CSRF) if "session" in request.scope else None
    recu = request.headers.get(EN_TETE_CSRF)
    if not recu:
        formulaire = await request.form()
        valeur = formulaire.get(NOM_CHAMP_CSRF)
        recu = valeur if isinstance(valeur, str) else None
    if not attendu or not recu or not hmac.compare_digest(str(attendu), recu):
        raise CSRFInvalide()


def regenerer_session(request: Request) -> str:
    """Anti-fixation de session : vide la session et crée un nouveau jeton CSRF (à appeler à la connexion)."""
    request.session.clear()
    return obtenir_jeton_csrf(request)


# ---------------------------------------------------------------------------
# Chiffrement des secrets OTP (Fernet, clé dérivée de SECRET_KEY par HKDF-SHA256)
# ---------------------------------------------------------------------------


@lru_cache
def _fernet() -> Fernet:
    cle = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"ika-compteur",
        info=b"chiffrement-secrets-otp",
    ).derive(settings.SECRET_KEY.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(cle))


def chiffrer_secret(secret: str) -> str:
    """Chiffre un secret (ex. secret TOTP) pour stockage en base."""
    return _fernet().encrypt(secret.encode("utf-8")).decode("ascii")


def dechiffrer_secret(secret_chiffre: str) -> str:
    """Déchiffre un secret stocké. Lève ValueError si le contenu est invalide ou la clé a changé."""
    try:
        return _fernet().decrypt(secret_chiffre.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise ValueError("Secret chiffré illisible.") from exc


# ---------------------------------------------------------------------------
# Limitation de débit en mémoire (par processus)
# ---------------------------------------------------------------------------


class TropDeRequetes(HTTPException):
    """429 avec en-tête Retry-After (rendu par la page erreurs/429.html)."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, int(retry_after))
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Trop de tentatives en peu de temps. Par sécurité, les nouvelles tentatives "
                "sont temporairement bloquées."
            ),
            headers={"Retry-After": str(self.retry_after)},
        )


class LimiteurDebit:
    """Fenêtre glissante : au plus `max_tentatives` par clé sur `fenetre_secondes`.

    Limitation connue : l'état est en mémoire, propre à chaque processus (non partagé entre workers).
    """

    def __init__(self, max_tentatives: int, fenetre_secondes: int) -> None:
        self.max_tentatives = max_tentatives
        self.fenetre_secondes = fenetre_secondes
        self._tentatives: dict[str, deque[float]] = {}
        self._verrou = threading.Lock()
        self._dernier_nettoyage = time.monotonic()

    def _purger(self, cle: str, instant: float) -> deque[float]:
        file = self._tentatives.setdefault(cle, deque())
        limite = instant - self.fenetre_secondes
        while file and file[0] <= limite:
            file.popleft()
        return file

    def _nettoyer(self, instant: float) -> None:
        if instant - self._dernier_nettoyage < self.fenetre_secondes:
            return
        limite = instant - self.fenetre_secondes
        for cle in [c for c, f in self._tentatives.items() if not f or f[-1] <= limite]:
            del self._tentatives[cle]
        self._dernier_nettoyage = instant

    def attente(self, cle: str) -> int:
        """Secondes à attendre avant une nouvelle tentative (0 si autorisée)."""
        instant = time.monotonic()
        with self._verrou:
            file = self._purger(cle, instant)
            if len(file) < self.max_tentatives:
                return 0
            return max(1, math.ceil(file[0] + self.fenetre_secondes - instant))

    def enregistrer(self, cle: str) -> None:
        instant = time.monotonic()
        with self._verrou:
            self._nettoyer(instant)
            self._purger(cle, instant).append(instant)

    def reinitialiser(self, cle: str) -> None:
        with self._verrou:
            self._tentatives.pop(cle, None)

    def vider(self) -> None:
        with self._verrou:
            self._tentatives.clear()


def consommer_limites(*limites: tuple[LimiteurDebit, str]) -> None:
    """Vérifie toutes les limites puis enregistre la tentative ; lève TropDeRequetes si l'une est atteinte."""
    attente = max((limiteur.attente(cle) for limiteur, cle in limites), default=0)
    if attente > 0:
        raise TropDeRequetes(attente)
    for limiteur, cle in limites:
        limiteur.enregistrer(cle)


limiteur_connexion_ip = LimiteurDebit(max_tentatives=20, fenetre_secondes=15 * 60)
limiteur_connexion_email = LimiteurDebit(max_tentatives=10, fenetre_secondes=15 * 60)
limiteur_otp_ip = LimiteurDebit(max_tentatives=10, fenetre_secondes=5 * 60)
limiteur_otp_utilisateur = LimiteurDebit(max_tentatives=5, fenetre_secondes=5 * 60)

LIMITEURS = (limiteur_connexion_ip, limiteur_connexion_email, limiteur_otp_ip, limiteur_otp_utilisateur)


def limiter_connexion(request: Request, email: str) -> None:
    """À appeler au début de POST /connexion (par IP et par e-mail)."""
    consommer_limites(
        (limiteur_connexion_ip, adresse_ip_client(request) or "inconnue"),
        (limiteur_connexion_email, email.strip().lower()),
    )


def reinitialiser_limite_connexion(email: str) -> None:
    """À appeler après une connexion réussie."""
    limiteur_connexion_email.reinitialiser(email.strip().lower())


def limiter_otp(request: Request, utilisateur_id: uuid.UUID | str) -> None:
    """À appeler au début de POST /otp/verification (par IP et par utilisateur)."""
    consommer_limites(
        (limiteur_otp_ip, adresse_ip_client(request) or "inconnue"),
        (limiteur_otp_utilisateur, str(utilisateur_id)),
    )


def reinitialiser_limite_otp(utilisateur_id: uuid.UUID | str) -> None:
    """À appeler après une vérification OTP réussie."""
    limiteur_otp_utilisateur.reinitialiser(str(utilisateur_id))


def vider_limiteurs() -> None:
    """Remet à zéro tous les limiteurs (utile pour les tests)."""
    for limiteur in LIMITEURS:
        limiteur.vider()


# ---------------------------------------------------------------------------
# Utilitaires de requête
# ---------------------------------------------------------------------------


def adresse_ip_client(request: Request) -> str | None:
    """Adresse IP du client (uvicorn --proxy-headers gère X-Forwarded-For derrière un proxy de confiance)."""
    return request.client.host if request.client else None


def url_redirection_sure(valeur: str | None, defaut: str = "/tableau-de-bord") -> str:
    """Retourne `valeur` uniquement si c'est un chemin local (anti redirection ouverte)."""
    if not valeur or not valeur.startswith("/") or valeur.startswith("//") or "\\" in valeur:
        return defaut
    if any(ord(c) < 32 for c in valeur):
        return defaut
    return valeur


# ---------------------------------------------------------------------------
# En-têtes de sécurité HTTP
# ---------------------------------------------------------------------------

CSP_STRICTE = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self' ws: wss:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)
# Uniquement pour /docs et /redoc (Swagger UI / ReDoc servis par FastAPI : CDN jsdelivr + script inline).
CSP_DOCUMENTATION = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly; "
    "font-src 'self' https://fonts.gstatic.com; worker-src 'self' blob:; connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)
CHEMINS_DOCUMENTATION = ("/docs", "/redoc")


def entetes_securite(chemin: str) -> dict[str, str]:
    """En-têtes de sécurité appliqués à toutes les réponses."""
    documentation = any(chemin == c or chemin.startswith(c + "/") for c in CHEMINS_DOCUMENTATION)
    return {
        "Content-Security-Policy": CSP_DOCUMENTATION if documentation else CSP_STRICTE,
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
    }


class EntetesSecuriteMiddleware:
    """Middleware ASGI ajoutant les en-têtes de sécurité à chaque réponse HTTP."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        entetes = entetes_securite(scope["path"])

        async def envoyer(message: Message) -> None:
            if message["type"] == "http.response.start":
                en_tetes = MutableHeaders(scope=message)
                for nom, valeur in entetes.items():
                    en_tetes[nom] = valeur
            await send(message)

        await self.app(scope, receive, envoyer)
