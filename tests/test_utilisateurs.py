"""CRUD des utilisateurs, garde-fous, entrées d'historique, permissions par rôle, menu et en-tête."""

import uuid

import httpx
import pytest

from app.core.database import SessionLocal
from app.core.security import verifier_mot_de_passe
from app.historique.model import ActionHistorique
from app.utilisateur import services
from app.utilisateur.model import Role, User
from conftest import EMAIL_ADMIN, MOT_DE_PASSE, contenu, entrees_historique, lire_compte, poster

FORMULAIRE_CREATION = {
    "nom_complet": "Paul Nouveau",
    "email": "Paul.Nouveau@IkaDemo.com",
    "telephone": "+226 70 12 34 56",
    "role": "MANAGER",
    "est_actif": "true",
    "mot_de_passe": MOT_DE_PASSE,
    "confirmation_mot_de_passe": MOT_DE_PASSE,
}
CLES_SENSIBLES = ("mot_de_passe", "hash", "secret", "jeton", "token", "password", "csrf")


def sans_donnees_sensibles(donnees: dict | None) -> bool:
    return not any(fragment in cle for cle in (donnees or {}) for fragment in CLES_SENSIBLES)


# ---------------------------------------------------------------------------
# CRUD (ADMIN)
# ---------------------------------------------------------------------------


async def test_creation(client_admin: httpx.AsyncClient, admin: User) -> None:
    reponse = await poster(client_admin, "/utilisateurs/ajouter", FORMULAIRE_CREATION)
    assert reponse.status_code == 303

    compte = await lire_compte("paul.nouveau@ikademo.com")
    assert compte is not None
    assert reponse.headers["location"] == f"/utilisateurs/{compte.id}"
    assert compte.role == Role.MANAGER and compte.est_actif
    assert verifier_mot_de_passe(MOT_DE_PASSE, compte.mot_de_passe_hash)

    fiche = await client_admin.get(reponse.headers["location"])
    assert fiche.status_code == 200
    assert "a été créé avec succès" in contenu(fiche)

    creation = (await entrees_historique(ActionHistorique.CREATION))[0]
    assert creation.module == "utilisateur"
    assert creation.utilisateur_id == admin.id  # auteur de l'action
    assert creation.objet_id == str(compte.id)
    assert creation.donnees_apres["email"] == "paul.nouveau@ikademo.com"
    assert sans_donnees_sensibles(creation.donnees_apres)
    assert MOT_DE_PASSE not in str(creation.donnees_apres)


async def test_creation_mot_de_passe_faible(client_admin: httpx.AsyncClient) -> None:
    reponse = await poster(
        client_admin,
        "/utilisateurs/ajouter",
        {**FORMULAIRE_CREATION, "mot_de_passe": "faible", "confirmation_mot_de_passe": "faible"},
    )
    assert reponse.status_code == 400
    page = contenu(reponse)
    assert "au moins 10 caractères" in page
    assert "Paul Nouveau" in page  # saisie conservée
    assert await lire_compte("paul.nouveau@ikademo.com") is None


async def test_creation_email_deja_utilise(client_admin: httpx.AsyncClient) -> None:
    reponse = await poster(client_admin, "/utilisateurs/ajouter", {**FORMULAIRE_CREATION, "email": EMAIL_ADMIN.upper()})
    assert reponse.status_code == 400
    assert "Cette adresse e-mail est déjà utilisée par un autre compte." in contenu(reponse)


async def test_creation_champs_obligatoires(client_admin: httpx.AsyncClient) -> None:
    reponse = await poster(client_admin, "/utilisateurs/ajouter", {"role": "INCONNU"})
    assert reponse.status_code == 400
    page = contenu(reponse)
    assert "Le formulaire contient des erreurs." in page
    assert "La valeur choisie n'est pas autorisée." in page


async def test_modification(client_admin: httpx.AsyncClient, admin: User, utilisateur_simple: User) -> None:
    url = f"/utilisateurs/{utilisateur_simple.id}/modifier"
    formulaire = await client_admin.get(url)
    assert formulaire.status_code == 200 and "Ursule Utilisatrice" in contenu(formulaire)

    reponse = await poster(
        client_admin,
        url,
        {"nom_complet": "Ursule Promue", "email": utilisateur_simple.email, "telephone": "", "role": "MANAGER",
         "est_actif": "true"},
    )
    assert reponse.status_code == 303 and reponse.headers["location"] == f"/utilisateurs/{utilisateur_simple.id}"

    compte = await lire_compte(utilisateur_simple.email)
    assert compte.nom_complet == "Ursule Promue" and compte.role == Role.MANAGER

    modification = (await entrees_historique(ActionHistorique.MODIFICATION))[0]
    assert modification.utilisateur_id == admin.id
    assert modification.donnees_avant["role"] == "UTILISATEUR" and modification.donnees_apres["role"] == "MANAGER"
    assert modification.donnees_avant["nom_complet"] == "Ursule Utilisatrice"
    assert sans_donnees_sensibles(modification.donnees_avant) and sans_donnees_sensibles(modification.donnees_apres)


async def test_suppression(client_admin: httpx.AsyncClient, admin: User, utilisateur_simple: User) -> None:
    fiche = await client_admin.get(f"/utilisateurs/{utilisateur_simple.id}")
    assert "data-confirmer-suppression" in fiche.text  # confirmation par modal
    assert 'id="modal-suppression"' in fiche.text

    reponse = await poster(client_admin, f"/utilisateurs/{utilisateur_simple.id}/supprimer")
    assert reponse.status_code == 303 and reponse.headers["location"] == "/utilisateurs"
    assert await lire_compte(utilisateur_simple.email) is None
    assert "a été supprimé définitivement" in contenu(await client_admin.get("/utilisateurs"))

    suppression = (await entrees_historique(ActionHistorique.SUPPRESSION))[0]
    assert suppression.utilisateur_id == admin.id
    assert suppression.objet_id == str(utilisateur_simple.id)
    assert suppression.donnees_avant["email"] == utilisateur_simple.email
    assert sans_donnees_sensibles(suppression.donnees_avant)


async def test_suppression_en_get_impossible(client_admin: httpx.AsyncClient, utilisateur_simple: User) -> None:
    assert (await client_admin.get(f"/utilisateurs/{utilisateur_simple.id}/supprimer")).status_code == 405


async def test_impossible_de_se_supprimer_soi_meme(client_admin: httpx.AsyncClient, admin: User) -> None:
    reponse = await poster(client_admin, f"/utilisateurs/{admin.id}/supprimer")
    assert reponse.status_code == 303
    assert "Vous ne pouvez pas supprimer votre propre compte." in contenu(await client_admin.get(reponse.headers["location"]))
    assert await lire_compte(EMAIL_ADMIN) is not None


@pytest.mark.parametrize(
    ("role", "est_actif", "action"),
    [("MANAGER", "true", "retirer le rôle Administrateur"), ("ADMIN", None, "désactiver")],
)
async def test_dernier_admin_actif_protege(
    client_admin: httpx.AsyncClient, admin: User, role: str, est_actif: str | None, action: str
) -> None:
    donnees = {"nom_complet": admin.nom_complet, "email": admin.email, "telephone": "", "role": role}
    if est_actif:
        donnees["est_actif"] = est_actif
    reponse = await poster(client_admin, f"/utilisateurs/{admin.id}/modifier", donnees)
    assert reponse.status_code == 400
    assert f"Impossible de {action}" in contenu(reponse) and "dernier administrateur actif" in contenu(reponse)
    compte = await lire_compte(EMAIL_ADMIN)
    assert compte.role == Role.ADMIN and compte.est_actif


async def test_dernier_admin_ne_peut_pas_etre_supprime(admin: User, manager: User) -> None:
    # Cas inatteignable par l'interface (l'auteur serait lui-même un administrateur actif) :
    # le garde-fou est vérifié directement sur le service.
    async with SessionLocal() as db:
        compte = await db.get(User, admin.id)
        auteur = await db.get(User, manager.id)
        with pytest.raises(services.ActionInterdite, match="dernier administrateur actif"):
            await services.supprimer_utilisateur(db, compte, auteur=auteur, request=None)
    assert await lire_compte(EMAIL_ADMIN) is not None


async def test_un_admin_peut_retrograder_un_autre_admin(client_admin: httpx.AsyncClient, creer_compte) -> None:
    autre = await creer_compte("second.admin@ikademo.com", Role.ADMIN, nom_complet="Second Admin")
    reponse = await poster(
        client_admin,
        f"/utilisateurs/{autre.id}/modifier",
        {"nom_complet": autre.nom_complet, "email": autre.email, "telephone": "", "role": "MANAGER", "est_actif": "true"},
    )
    assert reponse.status_code == 303
    assert (await lire_compte(autre.email)).role == Role.MANAGER


async def test_detail_introuvable(client_admin: httpx.AsyncClient) -> None:
    inconnu = await client_admin.get(f"/utilisateurs/{uuid.uuid4()}")
    assert inconnu.status_code == 404
    assert "L'utilisateur demandé n'existe pas ou a été supprimé." in contenu(inconnu)
    assert (await client_admin.get("/utilisateurs/pas-un-uuid")).status_code == 404


# ---------------------------------------------------------------------------
# Permissions par rôle
# ---------------------------------------------------------------------------

LECTURE = ["/utilisateurs", "/utilisateurs/export/pdf", "/utilisateurs/export/excel", "/historique",
           "/historique/export/pdf", "/historique/export/excel"]


async def test_manager_lecture_seule(client_manager: httpx.AsyncClient, utilisateur_simple: User) -> None:
    for chemin in [*LECTURE, f"/utilisateurs/{utilisateur_simple.id}", "/tableau-de-bord", "/profil"]:
        assert (await client_manager.get(chemin)).status_code == 200, chemin

    for chemin in ("/utilisateurs/ajouter", f"/utilisateurs/{utilisateur_simple.id}/modifier"):
        reponse = await client_manager.get(chemin)
        assert reponse.status_code == 403, chemin
        assert "Vous n'avez pas les droits nécessaires" in contenu(reponse)

    for chemin, donnees in (
        ("/utilisateurs/ajouter", FORMULAIRE_CREATION),
        (f"/utilisateurs/{utilisateur_simple.id}/modifier", {"nom_complet": "Pirate"}),
        (f"/utilisateurs/{utilisateur_simple.id}/supprimer", {}),
        (f"/utilisateurs/{utilisateur_simple.id}/deverrouiller", {}),
        (f"/utilisateurs/{utilisateur_simple.id}/reinitialiser-otp", {}),
    ):
        assert (await poster(client_manager, chemin, donnees)).status_code == 403, chemin

    assert (await lire_compte(utilisateur_simple.email)).nom_complet == "Ursule Utilisatrice"
    assert await lire_compte("paul.nouveau@ikademo.com") is None

    liste = contenu(await client_manager.get("/utilisateurs"))
    assert "/utilisateurs/ajouter" not in liste and "data-confirmer-suppression" not in liste


async def test_utilisateur_sans_acces_administration(client_utilisateur: httpx.AsyncClient, admin: User) -> None:
    for chemin in (*LECTURE, "/utilisateurs/ajouter", f"/utilisateurs/{admin.id}", f"/historique/{uuid.uuid4()}"):
        assert (await client_utilisateur.get(chemin)).status_code == 403, chemin
    assert (await poster(client_utilisateur, f"/utilisateurs/{admin.id}/supprimer")).status_code == 403
    for chemin in ("/tableau-de-bord", "/profil", "/otp/configuration"):
        assert (await client_utilisateur.get(chemin)).status_code == 200, chemin


@pytest.mark.parametrize(
    "chemin", ["/tableau-de-bord", "/profil", "/otp/configuration", "/utilisateurs", "/utilisateurs/ajouter",
               "/historique", "/utilisateurs/export/pdf", "/historique/export/excel"]
)
async def test_visiteur_redirige_vers_la_connexion(client: httpx.AsyncClient, chemin: str) -> None:
    reponse = await client.get(chemin)
    assert reponse.status_code == 303
    assert reponse.headers["location"].startswith("/connexion?suivant=")


# ---------------------------------------------------------------------------
# Menu et en-tête
# ---------------------------------------------------------------------------


async def test_menu_selon_le_role(
    client_admin: httpx.AsyncClient, client_manager: httpx.AsyncClient, client_utilisateur: httpx.AsyncClient
) -> None:
    page_admin = (await client_admin.get("/tableau-de-bord")).text
    for lien in ('href="/utilisateurs"', 'href="/utilisateurs/ajouter"', 'href="/historique"', 'href="/profil"'):
        assert lien in page_admin

    page_manager = (await client_manager.get("/tableau-de-bord")).text
    assert 'href="/utilisateurs"' in page_manager and 'href="/historique"' in page_manager
    assert 'href="/utilisateurs/ajouter"' not in page_manager

    page_utilisateur = (await client_utilisateur.get("/tableau-de-bord")).text
    assert 'href="/utilisateurs"' not in page_utilisateur and 'href="/historique"' not in page_utilisateur


@pytest.mark.parametrize(
    ("chemin", "lien_actif"),
    [("/tableau-de-bord", "/tableau-de-bord"), ("/utilisateurs", "/utilisateurs"),
     ("/utilisateurs/ajouter", "/utilisateurs/ajouter"), ("/historique", "/historique"), ("/profil", "/profil")],
)
async def test_lien_actif_du_menu(client_admin: httpx.AsyncClient, chemin: str, lien_actif: str) -> None:
    page = (await client_admin.get(chemin)).text
    assert f'<a class="menu-lien active" href="{lien_actif}" aria-current="page">' in page
    assert page.count('class="menu-lien active"') == 1


async def test_en_tete_avatar_profil_et_deconnexion(client_admin: httpx.AsyncClient) -> None:
    page = (await client_admin.get("/tableau-de-bord")).text
    entete = page[page.index('<header class="app-entete">'):page.index("</header>")]
    assert 'class="avatar-rond"' in entete and "bi-person-fill" in entete
    assert 'data-bs-toggle="dropdown"' in entete
    assert 'href="/profil"' in entete
    assert '<form method="post" action="/deconnexion">' in entete and 'name="csrf_token"' in entete
    assert 'data-bs-toggle="offcanvas"' in entete  # menu latéral en offcanvas sur mobile
