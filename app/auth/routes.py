"""Routes du module auth : connexion, vérification OTP, déconnexion, inscription,
mot de passe oublié / réinitialisation, profil et configuration de la double authentification.

La vérification CSRF est appliquée automatiquement à toutes les requêtes POST (app/main.py).
"""

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import FormData

from app.auth import otp, services
from app.auth.permissions import rediriger_si_connecte
from app.auth.schemas import (
    SchemaChangementMotDePasse,
    SchemaCodeOtp,
    SchemaConnexion,
    SchemaDesactivationOtp,
    SchemaInscription,
    SchemaMotDePasseOublie,
    SchemaProfil,
    SchemaReinitialisation,
)
from app.core.config import settings
from app.core.dependencies import DbSession, UtilisateurCourant, UtilisateurOptionnel
from app.core.security import (
    definir_cookie_jeton,
    limiter_connexion,
    limiter_otp,
    regenerer_session,
    reinitialiser_limite_otp,
    supprimer_cookie_jeton,
    url_redirection_sure,
)
from app.core.templating import flash, rendre
from app.core.validation import CHAMP_GENERAL, valider
from app.utilisateur.model import User

router = APIRouter(tags=["Authentification"])

# Pages affichant un secret ou un jeton : jamais mises en cache.
SANS_CACHE = {"Cache-Control": "no-store"}
LONGUEUR_MAX_CLE_LIMITE = 320


def _texte(formulaire: FormData, champ: str) -> str:
    """Valeur texte d'un champ de formulaire (chaîne vide si absent ou non textuel)."""
    valeur = formulaire.get(champ)
    return valeur if isinstance(valeur, str) else ""


def _rediriger(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _formulaire(
    request: Request,
    template: str,
    *,
    erreurs: Mapping[str, str] | None = None,
    valeurs: Mapping[str, Any] | None = None,
    status_code: int = 200,
    headers: Mapping[str, str] | None = None,
    **contexte: Any,
) -> Response:
    """Rend un formulaire (erreurs et valeurs toujours définies ; jamais de mot de passe dans valeurs)."""
    donnees = {"erreurs": dict(erreurs or {}), "valeurs": dict(valeurs or {}), **contexte}
    return rendre(request, template, donnees, status_code=status_code, headers=headers)


# ---------------------------------------------------------------------------
# Connexion
# ---------------------------------------------------------------------------


@router.get("/connexion", summary="Page de connexion")
async def page_connexion(
    request: Request, utilisateur: UtilisateurOptionnel, suivant: str | None = None
) -> Response:
    if redirection := rediriger_si_connecte(utilisateur):
        return redirection
    return _formulaire(request, "auth/connexion.html", suivant=url_redirection_sure(suivant, ""))


@router.post("/connexion", summary="Connexion (e-mail + mot de passe)")
async def connexion(request: Request, db: DbSession) -> Response:
    formulaire = await request.form()
    email_saisi = _texte(formulaire, "email").strip().lower()
    # Limitation de débit (par IP et par e-mail) avant tout traitement.
    limiter_connexion(request, email_saisi[:LONGUEUR_MAX_CLE_LIMITE])

    suivant = url_redirection_sure(_texte(formulaire, "suivant"), "")
    valeurs = {"email": email_saisi}
    donnees, erreurs = valider(SchemaConnexion, formulaire)
    if donnees is None:
        return _formulaire(
            request, "auth/connexion.html", erreurs=erreurs, valeurs=valeurs, suivant=suivant, status_code=400
        )

    resultat = await services.authentifier(db, request, donnees.email, donnees.mot_de_passe)
    if resultat.utilisateur is None:
        return _formulaire(
            request,
            "auth/connexion.html",
            erreurs={CHAMP_GENERAL: resultat.erreur or services.MESSAGE_IDENTIFIANTS_INVALIDES},
            valeurs=valeurs,
            suivant=suivant,
            status_code=401,
        )

    utilisateur = resultat.utilisateur
    if utilisateur.otp_active:
        # Mot de passe correct : nouvelle session, puis étape du code OTP avant d'émettre le JWT.
        regenerer_session(request)
        services.mettre_otp_en_attente(request, utilisateur, suivant)
        return _rediriger("/otp/verification")

    return await _connecter(request, db, utilisateur, suivant)


async def _connecter(
    request: Request, db: AsyncSession, utilisateur: User, suivant: str, *, double_authentification: bool = False
) -> Response:
    """Émet le JWT (session régénérée), pose le cookie et redirige vers la page demandée."""
    jeton = await services.ouvrir_session(db, request, utilisateur, double_authentification=double_authentification)
    flash(request, services.MESSAGE_CONNEXION_REUSSIE.format(nom=utilisateur.nom_complet), "success")
    reponse = _rediriger(url_redirection_sure(suivant))
    definir_cookie_jeton(reponse, jeton)
    return reponse


# ---------------------------------------------------------------------------
# Vérification OTP (deuxième étape de connexion)
# ---------------------------------------------------------------------------


@router.get("/otp/verification", summary="Page de saisie du code de double authentification")
async def page_otp_verification(request: Request, utilisateur: UtilisateurOptionnel) -> Response:
    if redirection := rediriger_si_connecte(utilisateur):
        return redirection
    if services.lire_otp_en_attente(request) is None:
        flash(request, services.MESSAGE_OTP_EXPIRE, "warning")
        return _rediriger("/connexion")
    return _formulaire(request, "auth/otp_verification.html")


@router.post("/otp/verification", summary="Vérification du code de double authentification")
async def otp_verification(request: Request, db: DbSession) -> Response:
    formulaire = await request.form()
    attente = services.lire_otp_en_attente(request)
    if attente is None:
        flash(request, services.MESSAGE_OTP_EXPIRE, "warning")
        return _rediriger("/connexion")
    # Limitation de débit (par IP et par utilisateur) avant toute vérification.
    limiter_otp(request, attente.utilisateur_id)

    donnees, erreurs = valider(SchemaCodeOtp, formulaire)
    if donnees is None:
        return _formulaire(request, "auth/otp_verification.html", erreurs=erreurs, status_code=400)

    resultat = await services.verifier_otp_connexion(db, request, attente.utilisateur_id, donnees.code)
    if resultat.utilisateur is None:
        message = resultat.erreur or services.MESSAGE_CODE_OTP_INVALIDE
        if resultat.abandonner:
            services.annuler_otp_en_attente(request)
            flash(request, message, "danger")
            return _rediriger("/connexion")
        return _formulaire(request, "auth/otp_verification.html", erreurs={"code": message}, status_code=401)

    reinitialiser_limite_otp(attente.utilisateur_id)
    return await _connecter(request, db, resultat.utilisateur, attente.suivant, double_authentification=True)


# ---------------------------------------------------------------------------
# Déconnexion
# ---------------------------------------------------------------------------


@router.post("/deconnexion", summary="Déconnexion (révocation du JWT)")
async def deconnexion(request: Request, db: DbSession, utilisateur: UtilisateurOptionnel) -> Response:
    if utilisateur is not None:
        await services.fermer_session(db, request, utilisateur)
    else:
        request.session.clear()
    flash(request, services.MESSAGE_DECONNEXION, "success")
    reponse = _rediriger("/connexion")
    supprimer_cookie_jeton(reponse)
    return reponse


# ---------------------------------------------------------------------------
# Inscription
# ---------------------------------------------------------------------------

CHAMPS_INSCRIPTION_CONSERVES = ("nom_complet", "email", "telephone")


@router.get("/inscription", summary="Page d'inscription")
async def page_inscription(request: Request, utilisateur: UtilisateurOptionnel) -> Response:
    if redirection := rediriger_si_connecte(utilisateur):
        return redirection
    return _formulaire(request, "auth/inscription.html")


@router.post("/inscription", summary="Création d'un compte (rôle Utilisateur)")
async def inscription(request: Request, db: DbSession, utilisateur: UtilisateurOptionnel) -> Response:
    if redirection := rediriger_si_connecte(utilisateur):
        return redirection
    formulaire = await request.form()
    valeurs = {champ: _texte(formulaire, champ) for champ in CHAMPS_INSCRIPTION_CONSERVES}
    donnees, erreurs = valider(SchemaInscription, formulaire)
    if donnees is None:
        return _formulaire(request, "auth/inscription.html", erreurs=erreurs, valeurs=valeurs, status_code=400)
    try:
        await services.inscrire(db, request, donnees)
    except services.EmailDejaUtilise:
        return _formulaire(
            request,
            "auth/inscription.html",
            erreurs={"email": services.MESSAGE_EMAIL_DEJA_UTILISE},
            valeurs=valeurs,
            status_code=400,
        )
    flash(request, services.MESSAGE_INSCRIPTION_REUSSIE, "success")
    return _rediriger("/connexion")


# ---------------------------------------------------------------------------
# Mot de passe oublié / réinitialisation
# ---------------------------------------------------------------------------


@router.get("/mot-de-passe-oublie", summary="Page de demande de réinitialisation du mot de passe")
async def page_mot_de_passe_oublie(request: Request, utilisateur: UtilisateurOptionnel) -> Response:
    if redirection := rediriger_si_connecte(utilisateur):
        return redirection
    return _formulaire(request, "auth/mot_de_passe_oublie.html")


@router.post("/mot-de-passe-oublie", summary="Envoi du lien de réinitialisation par e-mail")
async def mot_de_passe_oublie(
    request: Request, db: DbSession, utilisateur: UtilisateurOptionnel, taches: BackgroundTasks
) -> Response:
    if redirection := rediriger_si_connecte(utilisateur):
        return redirection
    formulaire = await request.form()
    donnees, erreurs = valider(SchemaMotDePasseOublie, formulaire)
    if donnees is None:
        return _formulaire(
            request,
            "auth/mot_de_passe_oublie.html",
            erreurs=erreurs,
            valeurs={"email": _texte(formulaire, "email").strip()},
            status_code=400,
        )
    demande = await services.demander_reinitialisation(db, request, donnees.email)
    if demande is not None:
        compte, jeton = demande
        # Envoi après la réponse : même temps de réponse que le compte existe ou non.
        taches.add_task(services.envoyer_email_reinitialisation, compte.email, compte.nom_complet, jeton)
    # Même message dans tous les cas (anti-énumération des comptes).
    flash(
        request,
        services.MESSAGE_DEMANDE_REINITIALISATION.format(
            email=donnees.email, minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES
        ),
        "info",
    )
    return _rediriger("/connexion")


@router.get("/mot-de-passe/reinitialiser", summary="Page de choix d'un nouveau mot de passe")
async def page_reinitialisation(
    request: Request, db: DbSession, utilisateur: UtilisateurOptionnel, jeton: str | None = None
) -> Response:
    if redirection := rediriger_si_connecte(utilisateur):
        return redirection
    try:
        await services.verifier_jeton_reinitialisation(db, jeton)
    except services.JetonInvalide as exc:
        return _formulaire(
            request, "auth/mot_de_passe_reinitialiser.html", erreur_jeton=exc.message,
            status_code=400, headers=SANS_CACHE,
        )
    return _formulaire(request, "auth/mot_de_passe_reinitialiser.html", jeton=jeton, headers=SANS_CACHE)


@router.post("/mot-de-passe/reinitialiser", summary="Enregistrement du nouveau mot de passe")
async def reinitialisation(request: Request, db: DbSession, utilisateur: UtilisateurOptionnel) -> Response:
    if redirection := rediriger_si_connecte(utilisateur):
        return redirection
    formulaire = await request.form()
    jeton = _texte(formulaire, "jeton")
    try:
        enregistrement, compte = await services.verifier_jeton_reinitialisation(db, jeton, verrouiller=True)
    except services.JetonInvalide as exc:
        return _formulaire(
            request, "auth/mot_de_passe_reinitialiser.html", erreur_jeton=exc.message,
            status_code=400, headers=SANS_CACHE,
        )
    donnees, erreurs = valider(SchemaReinitialisation, formulaire)
    if donnees is None:
        return _formulaire(
            request, "auth/mot_de_passe_reinitialiser.html", erreurs=erreurs, jeton=jeton,
            status_code=400, headers=SANS_CACHE,
        )
    await services.reinitialiser_mot_de_passe(db, request, enregistrement, compte, donnees.mot_de_passe)
    flash(request, services.MESSAGE_REINITIALISATION_REUSSIE, "success")
    return _rediriger("/connexion")


# ---------------------------------------------------------------------------
# Profil
# ---------------------------------------------------------------------------


def _rendre_profil(
    request: Request,
    utilisateur: User,
    *,
    erreurs_profil: Mapping[str, str] | None = None,
    valeurs_profil: Mapping[str, str] | None = None,
    erreurs_mot_de_passe: Mapping[str, str] | None = None,
    status_code: int = 200,
) -> Response:
    contexte = {
        "erreurs_profil": dict(erreurs_profil or {}),
        "valeurs_profil": dict(
            valeurs_profil or {"nom_complet": utilisateur.nom_complet, "telephone": utilisateur.telephone or ""}
        ),
        "erreurs_mot_de_passe": dict(erreurs_mot_de_passe or {}),
    }
    return rendre(request, "auth/profil.html", contexte, status_code=status_code)


@router.get("/profil", summary="Mon profil")
async def page_profil(request: Request, utilisateur: UtilisateurCourant) -> Response:
    return _rendre_profil(request, utilisateur)


@router.post("/profil", summary="Modification du nom et du téléphone")
async def profil(request: Request, db: DbSession, utilisateur: UtilisateurCourant) -> Response:
    formulaire = await request.form()
    donnees, erreurs = valider(SchemaProfil, formulaire)
    if donnees is None:
        valeurs = {champ: _texte(formulaire, champ) for champ in ("nom_complet", "telephone")}
        return _rendre_profil(request, utilisateur, erreurs_profil=erreurs, valeurs_profil=valeurs, status_code=400)
    if await services.modifier_profil(db, request, utilisateur, donnees):
        flash(request, services.MESSAGE_PROFIL_MODIFIE, "success")
    else:
        flash(request, services.MESSAGE_PROFIL_INCHANGE, "info")
    return _rediriger("/profil")


@router.post("/profil/mot-de-passe", summary="Changement du mot de passe (mot de passe actuel requis)")
async def changement_mot_de_passe(request: Request, db: DbSession, utilisateur: UtilisateurCourant) -> Response:
    formulaire = await request.form()
    donnees, erreurs = valider(SchemaChangementMotDePasse, formulaire)
    if donnees is None:
        return _rendre_profil(request, utilisateur, erreurs_mot_de_passe=erreurs, status_code=400)
    if not await services.changer_mot_de_passe(
        db, request, utilisateur, donnees.mot_de_passe_actuel, donnees.nouveau_mot_de_passe
    ):
        return _rendre_profil(
            request,
            utilisateur,
            erreurs_mot_de_passe={"mot_de_passe_actuel": services.MESSAGE_MOT_DE_PASSE_ACTUEL_INCORRECT},
            status_code=400,
        )
    flash(request, services.MESSAGE_MOT_DE_PASSE_MODIFIE, "success")
    return _rediriger("/profil")


# ---------------------------------------------------------------------------
# Configuration de la double authentification
# ---------------------------------------------------------------------------


def _rendre_configuration_otp(
    request: Request, utilisateur: User, *, erreurs: Mapping[str, str] | None = None, status_code: int = 200
) -> Response:
    contexte: dict[str, Any] = {}
    if not utilisateur.otp_active:
        secret = services.secret_otp_en_configuration(request)
        contexte = {
            "qr_code": otp.qr_code_data_uri(otp.uri_provisionnement(secret, utilisateur.email)),
            "secret_formate": otp.formater_secret(secret),
        }
    return _formulaire(
        request, "auth/otp_configuration.html", erreurs=erreurs, status_code=status_code, headers=SANS_CACHE,
        **contexte,
    )


@router.get("/otp/configuration", summary="Configuration de la double authentification")
async def page_configuration_otp(request: Request, utilisateur: UtilisateurCourant) -> Response:
    return _rendre_configuration_otp(request, utilisateur)


@router.post("/otp/configuration", summary="Activation de la double authentification (code requis)")
async def activation_otp(request: Request, db: DbSession, utilisateur: UtilisateurCourant) -> Response:
    if utilisateur.otp_active:
        flash(request, services.MESSAGE_OTP_DEJA_ACTIVEE, "info")
        return _rediriger("/otp/configuration")
    formulaire = await request.form()
    donnees, erreurs = valider(SchemaCodeOtp, formulaire)
    if donnees is None:
        return _rendre_configuration_otp(request, utilisateur, erreurs=erreurs, status_code=400)
    secret = services.secret_otp_en_configuration(request)
    if not otp.verifier_code(secret, donnees.code):
        return _rendre_configuration_otp(
            request, utilisateur, erreurs={"code": services.MESSAGE_CODE_OTP_INVALIDE}, status_code=400
        )
    await services.activer_otp(db, request, utilisateur, secret)
    flash(request, services.MESSAGE_OTP_ACTIVEE, "success")
    return _rediriger("/otp/configuration")


@router.post("/otp/desactivation", summary="Désactivation de la double authentification (mot de passe requis)")
async def desactivation_otp(request: Request, db: DbSession, utilisateur: UtilisateurCourant) -> Response:
    if not utilisateur.otp_active:
        flash(request, services.MESSAGE_OTP_DEJA_DESACTIVEE, "info")
        return _rediriger("/otp/configuration")
    formulaire = await request.form()
    donnees, erreurs = valider(SchemaDesactivationOtp, formulaire)
    if donnees is None:
        return _rendre_configuration_otp(request, utilisateur, erreurs=erreurs, status_code=400)
    if not await services.desactiver_otp(db, request, utilisateur, donnees.mot_de_passe_actuel):
        return _rendre_configuration_otp(
            request,
            utilisateur,
            erreurs={"mot_de_passe_actuel": services.MESSAGE_MOT_DE_PASSE_ACTUEL_INCORRECT},
            status_code=400,
        )
    flash(request, services.MESSAGE_OTP_DESACTIVEE, "success")
    return _rediriger("/otp/configuration")
