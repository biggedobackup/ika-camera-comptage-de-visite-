"""Module historique : lecture seule, liste, détail, filtres et absence de données sensibles."""

import json
import uuid

import httpx
import pyotp
import pytest

from app.core.database import SessionLocal
from app.core.security import chiffrer_secret
from app.historique.model import ActionHistorique
from app.historique.services import journaliser, nettoyer_donnees
from app.main import app as application
from app.utilisateur.model import User
from conftest import MOT_DE_PASSE, contenu, entrees_historique, poster, se_connecter


# ---------------------------------------------------------------------------
# Lecture seule
# ---------------------------------------------------------------------------


def test_aucune_route_d_ecriture_sur_l_historique() -> None:
    chemins = application.openapi()["paths"]
    for chemin, operations in chemins.items():
        if chemin.startswith("/historique"):
            assert set(operations) == {"get"}, chemin


@pytest.mark.parametrize("methode", ["POST", "PUT", "PATCH", "DELETE"])
async def test_historique_refuse_toute_ecriture(client_admin: httpx.AsyncClient, methode: str) -> None:
    entree = (await entrees_historique(ActionHistorique.CONNEXION))[0]
    for chemin in ("/historique", f"/historique/{entree.id}"):
        reponse = await client_admin.request(methode, chemin)
        assert reponse.status_code == 405, (methode, chemin)
    assert len(await entrees_historique()) == 1


async def test_page_liste_sans_bouton_d_ajout(client_admin: httpx.AsyncClient) -> None:
    page = contenu(await client_admin.get("/historique"))
    assert "ne peuvent pas être modifiées" in page
    principal = page[page.index('<main id="contenu-principal"'):page.index("</main>")]
    assert "/historique/ajouter" not in principal and "data-confirmer-suppression" not in principal
    assert '<form method="post"' not in principal


# ---------------------------------------------------------------------------
# Liste et détail
# ---------------------------------------------------------------------------


async def test_liste_et_detail(client_admin: httpx.AsyncClient, admin: User) -> None:
    page = await client_admin.get("/historique")
    assert page.status_code == 200
    assert "Connexion réussie de admin@ikademo.com." in contenu(page)

    entree = (await entrees_historique(ActionHistorique.CONNEXION))[0]
    detail = await client_admin.get(f"/historique/{entree.id}")
    assert detail.status_code == 200
    texte = contenu(detail)
    assert "Détail de l'historique" in texte and "Connexion réussie de admin@ikademo.com." in texte
    assert f'href="/utilisateurs/{admin.id}"' in texte  # auteur lié à sa fiche
    assert "127.0.0.1" in texte  # adresse IP


async def test_detail_avant_apres(client_admin: httpx.AsyncClient, utilisateur_simple: User) -> None:
    await poster(
        client_admin,
        f"/utilisateurs/{utilisateur_simple.id}/modifier",
        {"nom_complet": "Nom Changé", "email": utilisateur_simple.email, "role": "UTILISATEUR", "est_actif": "true"},
    )
    entree = (await entrees_historique(ActionHistorique.MODIFICATION))[0]
    texte = contenu(await client_admin.get(f"/historique/{entree.id}"))
    assert "Ursule Utilisatrice" in texte and "Nom Changé" in texte
    assert "Modifié" in texte


async def test_detail_introuvable(client_admin: httpx.AsyncClient) -> None:
    reponse = await client_admin.get(f"/historique/{uuid.uuid4()}")
    assert reponse.status_code == 404
    assert "Cette entrée de l'historique n'existe pas." in contenu(reponse)
    assert (await client_admin.get("/historique/123")).status_code == 404


async def test_filtres(client_admin: httpx.AsyncClient, client: httpx.AsyncClient) -> None:
    await se_connecter(client, "inconnu@ikademo.com", "Mauvais#Passe1")
    connexions = contenu(await client_admin.get("/historique?action=CONNEXION"))
    assert "Connexion réussie de admin@ikademo.com." in connexions
    assert "aucun compte n'existe" not in connexions

    echecs = contenu(await client_admin.get("/historique?action=ECHEC_CONNEXION&module=auth"))
    assert "aucun compte n'existe pour l'adresse inconnu@ikademo.com" in echecs
    assert "Connexion réussie" not in echecs

    invalide = await client_admin.get("/historique?du=pas-une-date&action=INCONNUE")
    assert invalide.status_code == 200
    texte = contenu(invalide)
    assert "Certains filtres sont invalides et n'ont pas été appliqués" in texte
    assert "Filtre « Du » ignoré" in texte and "Filtre « Action » ignoré" in texte

    periode = contenu(await client_admin.get("/historique?du=2026-12-31&au=2026-01-01"))
    assert "La date « Du » doit être antérieure ou égale à la date « Au »." in periode


# ---------------------------------------------------------------------------
# Jamais de mot de passe, hash, jeton ni secret dans l'historique
# ---------------------------------------------------------------------------


def test_nettoyage_recursif_des_cles_sensibles() -> None:
    donnees = {
        "nom": "A",
        "mot_de_passe": "x",
        "mot_de_passe_hash": "x",
        "otp_secret_chiffre": "x",
        "csrf_token": "x",
        "imbrique": {"password": "x", "jeton": "x", "garde": 1, "liste": [{"token": "x", "ok": True}]},
    }
    assert nettoyer_donnees(donnees) == {"nom": "A", "imbrique": {"garde": 1, "liste": [{"ok": True}]}}


async def test_journaliser_filtre_les_secrets(admin: User) -> None:
    async with SessionLocal() as db:
        await journaliser(
            db,
            action=ActionHistorique.MODIFICATION,
            module="test",
            description="Essai",
            utilisateur=admin,
            donnees_avant={"mot_de_passe_hash": "$2b$12$abc", "nom_complet": "A"},
            donnees_apres={"otp_secret_chiffre": "gAAAA", "nom_complet": "B"},
        )
        await db.commit()
    entree = (await entrees_historique(ActionHistorique.MODIFICATION))[0]
    assert entree.donnees_avant == {"nom_complet": "A"} and entree.donnees_apres == {"nom_complet": "B"}


async def test_aucun_secret_apres_un_parcours_complet(
    client_admin: httpx.AsyncClient, client_utilisateur: httpx.AsyncClient, utilisateur_simple: User
) -> None:
    secret_otp = pyotp.random_base32(length=32)
    nouveau = "Autre#MotDePasse2026"
    await poster(
        client_admin,
        "/utilisateurs/ajouter",
        {"nom_complet": "Zoé Test", "email": "zoe@ikademo.com", "role": "UTILISATEUR", "est_actif": "true",
         "mot_de_passe": MOT_DE_PASSE, "confirmation_mot_de_passe": MOT_DE_PASSE},
    )
    await poster(
        client_utilisateur,
        "/profil/mot-de-passe",
        {"mot_de_passe_actuel": MOT_DE_PASSE, "nouveau_mot_de_passe": nouveau, "confirmation": nouveau},
    )
    async with SessionLocal() as db:
        compte = await db.get(User, utilisateur_simple.id)
        compte.otp_secret_chiffre = chiffrer_secret(secret_otp)
        await db.commit()
    await poster(client_admin, f"/utilisateurs/{utilisateur_simple.id}/reinitialiser-otp")

    entrees = await entrees_historique()
    assert len(entrees) >= 5
    for entree in entrees:
        texte = json.dumps(
            [entree.description, entree.donnees_avant, entree.donnees_apres], ensure_ascii=False, default=str
        )
        for interdit in (MOT_DE_PASSE, nouveau, secret_otp, "$2b$", "mot_de_passe", "hash", "secret", "csrf"):
            assert interdit not in texte, (entree.action, interdit)
