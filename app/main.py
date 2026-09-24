"""Point d'entrée FastAPI : middlewares, fichiers statiques, gestionnaires d'erreurs et routers."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth.routes import router as auth_router
from app.core.config import DOSSIER_APP, settings
from app.core.database import engine
from app.core.exceptions import enregistrer_gestionnaires
from app.core.security import EN_TETE_CSRF, NOM_COOKIE_SESSION, EntetesSecuriteMiddleware, verifier_csrf
from app.camera.routes import api_router as camera_api_router, router as camera_ui_router
from app.historique.routes import router as historique_router
from app.tableau_de_bord.routes import router as tableau_de_bord_router
from app.utilisateur.routes import router as utilisateur_router


def configurer_journalisation() -> None:
    """Journaux applicatifs (logger « app ») sur la sortie standard."""
    journal = logging.getLogger("app")
    journal.setLevel(logging.DEBUG if settings.APP_DEBUG else logging.INFO)
    if not journal.handlers:
        gestionnaire = logging.StreamHandler()
        gestionnaire.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        journal.addHandler(gestionnaire)
        journal.propagate = False


configurer_journalisation()


@asynccontextmanager
async def cycle_de_vie(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    description="Compteur de visite IKA — documentation de l'API.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    debug=False,  # jamais de trace technique affichée
    lifespan=cycle_de_vie,
)

# Ordre d'exécution (du plus externe au plus interne) :
# en-têtes de sécurité → hôtes autorisés → CORS → session.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    session_cookie=NOM_COOKIE_SESSION,
    max_age=settings.SESSION_EXPIRE_MINUTES * 60,
    same_site="lax",
    https_only=settings.cookie_secure,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", EN_TETE_CSRF],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)
app.add_middleware(EntetesSecuriteMiddleware)

app.mount("/static", StaticFiles(directory=DOSSIER_APP / "static"), name="static")

enregistrer_gestionnaires(app)

# Endpoints machine-à-machine pour les caméras IoT (sans CSRF)
app.include_router(camera_api_router)

# Vérification CSRF appliquée à toutes les requêtes POST de tous les modules.
protection_csrf = [Depends(verifier_csrf)]
app.include_router(auth_router, dependencies=protection_csrf)
app.include_router(tableau_de_bord_router, dependencies=protection_csrf)
app.include_router(utilisateur_router, dependencies=protection_csrf)
app.include_router(historique_router, dependencies=protection_csrf)
app.include_router(camera_ui_router, dependencies=protection_csrf)


@app.get("/", include_in_schema=False)
async def accueil() -> RedirectResponse:
    return RedirectResponse("/tableau-de-bord", status_code=303)
