"""Configuration commune des tests.

- Base de test : TEST_DATABASE_URL (environnement ou .env), sinon la base de DATABASE_URL suffixée par « _test »
  (ex. ika_compteur → ika_compteur_test). Par sécurité, le nom doit se terminer par « _test ».
- Tables créées au début de la session, vidées avant chaque test, supprimées à la fin.
- Client httpx.AsyncClient + ASGITransport sur l'hôte autorisé 127.0.0.1.
- Limiteurs de débit remis à zéro entre les tests.
- Comptes par rôle (ADMIN, MANAGER, UTILISATEUR) et clients déjà connectés.
- Tous les tests tournent dans une seule boucle asyncio (pytest.ini) : le moteur SQLAlchemy est global.
"""

import html
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from dotenv import dotenv_values
from sqlalchemy.engine import make_url

RACINE_PROJET = Path(__file__).resolve().parents[1]


def _url_base_de_test() -> str:
    fichier_env = dotenv_values(RACINE_PROJET / ".env")
    url = os.environ.get("TEST_DATABASE_URL") or fichier_env.get("TEST_DATABASE_URL")
    if not url:
        url_dev = os.environ.get("DATABASE_URL") or fichier_env.get("DATABASE_URL")
        if not url_dev:
            raise RuntimeError("Définissez TEST_DATABASE_URL (ou DATABASE_URL dans .env) pour lancer les tests.")
        url_objet = make_url(url_dev)
        nom = url_objet.database or ""
        url = url_objet.set(database=nom if nom.endswith("_test") else f"{nom}_test").render_as_string(
            hide_password=False
        )
    if not (make_url(url).database or "").endswith("_test"):
        raise RuntimeError("Par sécurité, le nom de la base de test doit se terminer par « _test ».")
    return url


# Configuration imposée AVANT tout import de l'application.
os.environ["DATABASE_URL"] = _url_base_de_test()
os.environ["APP_ENV"] = "test"
os.environ["APP_DEBUG"] = "false"
os.environ["APP_BASE_URL"] = "http://127.0.0.1:8000"
os.environ["ALLOWED_HOSTS"] = "127.0.0.1,localhost"
os.environ["CORS_ORIGINS"] = ""
os.environ["COOKIE_SECURE"] = "false"  # tests en http://
os.environ["SMTP_HOST"] = ""  # aucun e-mail réellement envoyé
os.environ.setdefault("SECRET_KEY", "cle-secrete-de-test-longue-et-aleatoire-0123456789")

import httpx  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

import app.main  # noqa: E402,F401  (enregistre tous les modèles)
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.core.security import hacher_mot_de_passe, vider_limiteurs  # noqa: E402
from app.historique.model import ActionHistorique, Historique  # noqa: E402
from app.main import app as application  # noqa: E402
from app.utilisateur.model import Role, User  # noqa: E402

URL_BASE = "http://127.0.0.1:8000"
MOT_DE_PASSE = "Compteur@2026!"
EMAIL_ADMIN = "admin@ikademo.com"
EMAIL_MANAGER = "manager@ikademo.com"
EMAIL_UTILISATEUR = "utilisateur@ikademo.com"

_MOTIF_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')


# ---------------------------------------------------------------------------
# Base de données
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session", autouse=True)
async def base_de_test() -> AsyncIterator[None]:
    """Crée les tables au début de la session et les supprime à la fin."""
    async with engine.begin() as connexion:
        await connexion.run_sync(Base.metadata.drop_all)
        await connexion.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as connexion:
        await connexion.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def etat_propre(base_de_test: None) -> AsyncIterator[None]:
    """Chaque test démarre avec des tables vides et des limiteurs de débit remis à zéro."""
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    async with engine.begin() as connexion:
        await connexion.execute(text(f"TRUNCATE {tables} CASCADE"))
    vider_limiteurs()
    yield
    vider_limiteurs()


# ---------------------------------------------------------------------------
# Comptes
# ---------------------------------------------------------------------------


@lru_cache
def hash_mot_de_passe_commun() -> str:
    """Hash bcrypt de MOT_DE_PASSE, calculé une seule fois (bcrypt est volontairement lent)."""
    return hacher_mot_de_passe(MOT_DE_PASSE)


CreerCompte = Callable[..., Awaitable[User]]


@pytest.fixture
def creer_compte() -> CreerCompte:
    """Fabrique : `await creer_compte("x@ikademo.com", Role.MANAGER, nom_complet=..., est_actif=...)`."""

    async def _creer(email: str, role: Role = Role.UTILISATEUR, **champs: Any) -> User:
        valeurs: dict[str, Any] = {
            "nom_complet": email.split("@")[0].replace(".", " ").title(),
            "email": email.lower(),
            "mot_de_passe_hash": hash_mot_de_passe_commun(),
            "role": role,
            "est_actif": True,
        }
        valeurs.update(champs)
        async with SessionLocal() as db:
            compte = User(**valeurs)
            db.add(compte)
            await db.commit()
            return compte

    return _creer


@pytest_asyncio.fixture
async def admin(creer_compte: CreerCompte) -> User:
    return await creer_compte(EMAIL_ADMIN, Role.ADMIN, nom_complet="Alice Admin")


@pytest_asyncio.fixture
async def manager(creer_compte: CreerCompte) -> User:
    return await creer_compte(EMAIL_MANAGER, Role.MANAGER, nom_complet="Marc Manager")


@pytest_asyncio.fixture
async def utilisateur_simple(creer_compte: CreerCompte) -> User:
    return await creer_compte(EMAIL_UTILISATEUR, Role.UTILISATEUR, nom_complet="Ursule Utilisatrice")


async def lire_compte(email: str) -> User | None:
    """Relit un compte en base (nouvelle session)."""
    async with SessionLocal() as db:
        return await db.scalar(select(User).where(User.email == email.lower()))


async def entrees_historique(action: ActionHistorique | None = None) -> list[Historique]:
    """Entrées de l'historique (les plus anciennes d'abord), éventuellement filtrées par action."""
    requete = select(Historique).order_by(Historique.created_at, Historique.id)
    if action is not None:
        requete = requete.where(Historique.action == action)
    async with SessionLocal() as db:
        return list((await db.scalars(requete)).all())


def contenu(reponse: httpx.Response) -> str:
    """Texte HTML de la réponse avec les entités décodées (&#39; → ')."""
    return html.unescape(reponse.text)


def texte_visible(reponse: httpx.Response) -> str:
    """Texte de la page sans balises, espaces normalisés (« <strong>3</strong> éléments » → « 3 éléments »)."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", reponse.text)).split())


# ---------------------------------------------------------------------------
# Clients HTTP
# ---------------------------------------------------------------------------


def nouveau_client(**options: Any) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url=URL_BASE, follow_redirects=False, **options)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """Client anonyme (cookies conservés entre ses requêtes)."""
    async with nouveau_client() as c:
        yield c


def extraire_csrf(html: str) -> str:
    """Jeton CSRF du premier formulaire de la page."""
    trouve = _MOTIF_CSRF.search(html)
    assert trouve, "Aucun champ csrf_token dans la page."
    return trouve.group(1)


async def obtenir_csrf(client: httpx.AsyncClient, chemin: str = "/connexion") -> str:
    """Charge une page contenant un formulaire POST et retourne le jeton CSRF de la session."""
    reponse = await client.get(chemin)
    assert reponse.status_code == 200, f"GET {chemin} → {reponse.status_code}"
    return extraire_csrf(reponse.text)


async def poster(
    client: httpx.AsyncClient, url: str, donnees: dict[str, Any] | None = None, *, page_csrf: str | None = None
) -> httpx.Response:
    """POST de formulaire avec le jeton CSRF lu sur `page_csrf` (par défaut : l'URL elle-même,
    ou /connexion pour un client anonyme, /profil pour un client connecté)."""
    if page_csrf is None:
        page_csrf = "/profil" if "ika_jeton" in client.cookies else "/connexion"
    formulaire = {"csrf_token": await obtenir_csrf(client, page_csrf), **(donnees or {})}
    return await client.post(url, data=formulaire)


async def se_connecter(
    client: httpx.AsyncClient, email: str, mot_de_passe: str = MOT_DE_PASSE, **champs: Any
) -> httpx.Response:
    """Soumet le formulaire de connexion (sans suivre la redirection)."""
    jeton = await obtenir_csrf(client, "/connexion")
    return await client.post(
        "/connexion", data={"csrf_token": jeton, "email": email, "mot_de_passe": mot_de_passe, **champs}
    )


async def connecter(client: httpx.AsyncClient, email: str, mot_de_passe: str = MOT_DE_PASSE) -> None:
    """Connexion qui doit réussir (cookie JWT posé)."""
    reponse = await se_connecter(client, email, mot_de_passe)
    assert reponse.status_code == 303 and "ika_jeton" in client.cookies, reponse.text[:500]


@pytest_asyncio.fixture
async def client_admin(admin: User) -> AsyncIterator[httpx.AsyncClient]:
    async with nouveau_client() as c:
        await connecter(c, admin.email)
        yield c


@pytest_asyncio.fixture
async def client_manager(manager: User) -> AsyncIterator[httpx.AsyncClient]:
    async with nouveau_client() as c:
        await connecter(c, manager.email)
        yield c


@pytest_asyncio.fixture
async def client_utilisateur(utilisateur_simple: User) -> AsyncIterator[httpx.AsyncClient]:
    async with nouveau_client() as c:
        await connecter(c, utilisateur_simple.email)
        yield c
