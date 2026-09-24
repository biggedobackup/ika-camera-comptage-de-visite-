"""Routes du module utilisateur.

- ADMIN : liste, fiche, création, modification, suppression, déverrouillage, réinitialisation OTP, exports.
- MANAGER : liste, fiche et exports (lecture seule).
Les routes fixes (/ajouter, /export/...) sont déclarées avant /utilisateurs/{utilisateur_id}.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.core.dependencies import DbSession
from app.core.listes import paginer
from app.core.security import NOM_CHAMP_CSRF
from app.core.templating import flash, rendre
from app.core.validation import valider
from app.utilisateur import services
from app.utilisateur.export_excel import exporter_excel
from app.utilisateur.export_pdf import exporter_pdf
from app.utilisateur.model import Role, User
from app.utilisateur.permissions import GestionnaireUtilisateurs, LecteurUtilisateurs, peut_gerer_utilisateurs
from app.utilisateur.schemas import UtilisateurCreation, UtilisateurModification

router = APIRouter(tags=["Utilisateurs"])

MESSAGE_INTROUVABLE = "L'utilisateur demandé n'existe pas ou a été supprimé."
CHAMPS_NON_REAFFICHES = frozenset({NOM_CHAMP_CSRF, "mot_de_passe", "confirmation_mot_de_passe"})


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------


async def _charger(db: DbSession, utilisateur_id: uuid.UUID) -> User:
    compte = await services.obtenir_utilisateur(db, utilisateur_id)
    if compte is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=MESSAGE_INTROUVABLE)
    return compte


def _url_fiche(utilisateur_id: uuid.UUID) -> str:
    return f"/utilisateurs/{utilisateur_id}"


def _redirection(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


def _valeurs_formulaire(formulaire: Mapping[str, Any]) -> dict[str, Any]:
    """Valeurs saisies à réafficher après une erreur (jamais les mots de passe ni le jeton CSRF)."""
    valeurs = {
        cle: valeur
        for cle, valeur in formulaire.items()
        if isinstance(valeur, str) and cle not in CHAMPS_NON_REAFFICHES
    }
    valeurs["est_actif"] = "est_actif" in formulaire
    return valeurs


def _valeurs_compte(compte: User) -> dict[str, Any]:
    return {
        "nom_complet": compte.nom_complet,
        "email": compte.email,
        "telephone": compte.telephone or "",
        "role": compte.role.value,
        "est_actif": compte.est_actif,
    }


def _rendre_formulaire(
    request: Request,
    *,
    compte: User | None,
    valeurs: Mapping[str, Any],
    erreurs: Mapping[str, str] | None = None,
    status_code: int = status.HTTP_200_OK,
) -> Response:
    """Formulaire commun à la création (compte=None) et à la modification."""
    return rendre(
        request,
        "utilisateur/ajoute.html",
        {
            "compte": compte,
            "modification": compte is not None,
            "valeurs": valeurs,
            "erreurs": erreurs or {},
            "options_roles": services.OPTIONS_ROLES,
        },
        status_code=status_code,
    )


# ---------------------------------------------------------------------------
# Liste
# ---------------------------------------------------------------------------


@router.get("/utilisateurs", response_class=HTMLResponse, summary="Liste des utilisateurs")
async def liste_utilisateurs(request: Request, db: DbSession, utilisateur: LecteurUtilisateurs) -> Response:
    parametres = services.lire_parametres(request)
    liste = await paginer(db, services.requete_utilisateurs(parametres), parametres)
    return rendre(
        request,
        "utilisateur/liste.html",
        {
            "liste": liste,
            "options_roles": services.OPTIONS_ROLES,
            "options_statuts": services.OPTIONS_STATUTS,
            "statut_compte": services.statut_compte,
            "peut_gerer": peut_gerer_utilisateurs(utilisateur),
        },
    )


# ---------------------------------------------------------------------------
# Création
# ---------------------------------------------------------------------------


@router.get("/utilisateurs/ajouter", response_class=HTMLResponse, summary="Formulaire de création")
async def formulaire_ajout(request: Request, utilisateur: GestionnaireUtilisateurs) -> Response:
    return _rendre_formulaire(request, compte=None, valeurs={"role": Role.UTILISATEUR.value, "est_actif": True})


@router.post("/utilisateurs/ajouter", response_class=HTMLResponse, summary="Créer un utilisateur")
async def ajouter_utilisateur(request: Request, db: DbSession, utilisateur: GestionnaireUtilisateurs) -> Response:
    formulaire = await request.form()
    donnees, erreurs = valider(UtilisateurCreation, formulaire)
    if donnees is None:
        return _rendre_formulaire(
            request, compte=None, valeurs=_valeurs_formulaire(formulaire), erreurs=erreurs, status_code=400
        )
    try:
        compte = await services.creer_utilisateur(db, donnees, auteur=utilisateur, request=request)
    except services.ErreurUtilisateur as erreur:
        return _rendre_formulaire(
            request,
            compte=None,
            valeurs=_valeurs_formulaire(formulaire),
            erreurs={erreur.champ: erreur.message},
            status_code=400,
        )
    flash(request, f"Le compte de {compte.nom_complet} ({compte.email}) a été créé avec succès.", "success")
    return _redirection(_url_fiche(compte.id))


# ---------------------------------------------------------------------------
# Exports (mêmes filtres et tri que la liste, toutes les lignes)
# ---------------------------------------------------------------------------


@router.get("/utilisateurs/export/pdf", summary="Export PDF des utilisateurs")
async def export_pdf(request: Request, db: DbSession, utilisateur: LecteurUtilisateurs) -> Response:
    return await exporter_pdf(request, db)


@router.get("/utilisateurs/export/excel", summary="Export Excel des utilisateurs")
async def export_excel(request: Request, db: DbSession, utilisateur: LecteurUtilisateurs) -> Response:
    return await exporter_excel(request, db)


# ---------------------------------------------------------------------------
# Fiche détail
# ---------------------------------------------------------------------------


@router.get("/utilisateurs/{utilisateur_id}", response_class=HTMLResponse, summary="Fiche d'un utilisateur")
async def detail_utilisateur(
    request: Request, db: DbSession, utilisateur: LecteurUtilisateurs, utilisateur_id: uuid.UUID
) -> Response:
    compte = await _charger(db, utilisateur_id)
    return rendre(
        request,
        "utilisateur/detail.html",
        {
            "compte": compte,
            "statut": services.statut_compte(compte),
            "peut_gerer": peut_gerer_utilisateurs(utilisateur),
            "est_soi_meme": compte.id == utilisateur.id,
        },
    )


# ---------------------------------------------------------------------------
# Modification
# ---------------------------------------------------------------------------


@router.get("/utilisateurs/{utilisateur_id}/modifier", response_class=HTMLResponse, summary="Formulaire de modification")
async def formulaire_modification(
    request: Request, db: DbSession, utilisateur: GestionnaireUtilisateurs, utilisateur_id: uuid.UUID
) -> Response:
    compte = await _charger(db, utilisateur_id)
    return _rendre_formulaire(request, compte=compte, valeurs=_valeurs_compte(compte))


@router.post("/utilisateurs/{utilisateur_id}/modifier", response_class=HTMLResponse, summary="Modifier un utilisateur")
async def modifier_utilisateur(
    request: Request, db: DbSession, utilisateur: GestionnaireUtilisateurs, utilisateur_id: uuid.UUID
) -> Response:
    compte = await _charger(db, utilisateur_id)
    formulaire = await request.form()
    donnees, erreurs = valider(UtilisateurModification, formulaire)
    if donnees is None:
        return _rendre_formulaire(
            request, compte=compte, valeurs=_valeurs_formulaire(formulaire), erreurs=erreurs, status_code=400
        )
    try:
        modifie = await services.modifier_utilisateur(db, compte, donnees, auteur=utilisateur, request=request)
    except services.ErreurUtilisateur as erreur:
        return _rendre_formulaire(
            request,
            compte=compte,
            valeurs=_valeurs_formulaire(formulaire),
            erreurs={erreur.champ: erreur.message},
            status_code=400,
        )
    if modifie:
        flash(request, f"Les informations de {compte.nom_complet} ont été mises à jour avec succès.", "success")
    else:
        flash(request, "Aucune modification enregistrée : les informations saisies sont identiques.", "info")
    return _redirection(_url_fiche(compte.id))


# ---------------------------------------------------------------------------
# Suppression (confirmée par la modal commune)
# ---------------------------------------------------------------------------


@router.post("/utilisateurs/{utilisateur_id}/supprimer", summary="Supprimer un utilisateur")
async def supprimer_utilisateur(
    request: Request, db: DbSession, utilisateur: GestionnaireUtilisateurs, utilisateur_id: uuid.UUID
) -> Response:
    compte = await _charger(db, utilisateur_id)
    nom, email = compte.nom_complet, compte.email
    try:
        await services.supprimer_utilisateur(db, compte, auteur=utilisateur, request=request)
    except services.ErreurUtilisateur as erreur:
        flash(request, erreur.message, "danger")
        return _redirection(_url_fiche(utilisateur_id))
    flash(request, f"Le compte de {nom} ({email}) a été supprimé définitivement.", "success")
    return _redirection("/utilisateurs")


# ---------------------------------------------------------------------------
# Sécurité du compte (depuis la fiche détail)
# ---------------------------------------------------------------------------


@router.post("/utilisateurs/{utilisateur_id}/deverrouiller", summary="Déverrouiller un compte")
async def deverrouiller_utilisateur(
    request: Request, db: DbSession, utilisateur: GestionnaireUtilisateurs, utilisateur_id: uuid.UUID
) -> Response:
    compte = await _charger(db, utilisateur_id)
    if await services.deverrouiller_utilisateur(db, compte, auteur=utilisateur, request=request):
        flash(
            request,
            f"Le compte de {compte.nom_complet} a été déverrouillé : il peut de nouveau se connecter.",
            "success",
        )
    else:
        flash(request, f"Le compte de {compte.nom_complet} n'est pas verrouillé : aucune action nécessaire.", "info")
    return _redirection(_url_fiche(compte.id))


@router.post("/utilisateurs/{utilisateur_id}/reinitialiser-otp", summary="Réinitialiser la double authentification")
async def reinitialiser_otp_utilisateur(
    request: Request, db: DbSession, utilisateur: GestionnaireUtilisateurs, utilisateur_id: uuid.UUID
) -> Response:
    compte = await _charger(db, utilisateur_id)
    if await services.reinitialiser_otp(db, compte, auteur=utilisateur, request=request):
        flash(
            request,
            f"La double authentification de {compte.nom_complet} a été réinitialisée : "
            "la connexion se fait désormais avec le mot de passe seul, jusqu'à une nouvelle configuration.",
            "success",
        )
    else:
        flash(
            request,
            f"La double authentification de {compte.nom_complet} n'est pas activée : aucune action nécessaire.",
            "info",
        )
    return _redirection(_url_fiche(compte.id))
