"""Connexion, verrouillage, limitation de débit, déconnexion, inscription, mot de passe oublié,
réinitialisation, profil et politique de mot de passe."""

import re
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import select, update

from app.auth.model import JetonReinitialisation, JetonRevoque
from app.core.database import SessionLocal, maintenant
from app.core.security import (
    DUREE_VERROUILLAGE_MINUTES,
    MAX_TENTATIVES_CONNEXION,
    erreurs_politique_mot_de_passe,
    hacher_jeton,
    verifier_mot_de_passe,
)
from app.historique.model import ActionHistorique
from app.utilisateur.model import Role, User
from conftest import (
    EMAIL_ADMIN,
    EMAIL_UTILISATEUR,
    MOT_DE_PASSE,
    connecter,
    contenu,
    entrees_historique,
    extraire_csrf,
    lire_compte,
    nouveau_client,
    obtenir_csrf,
    poster,
    se_connecter,
)

NOUVEAU_MOT_DE_PASSE = "Nouveau#Secret2026"
MESSAGE_IDENTIFIANTS = "Adresse e-mail ou mot de passe incorrect."


async def modifier_compte(email: str, **valeurs: object) -> None:
    async with SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(**valeurs))
        await db.commit()


# ---------------------------------------------------------------------------
# Politique de mot de passe
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mot_de_passe", "attendu"),
    [
        ("Court1!a", "au moins 10 caractères"),
        ("sansmajuscule1!", "majuscule"),
        ("SANSMINUSCULE1!", "minuscule"),
        ("SansChiffre!!!", "chiffre"),
        ("SansSpecial1234", "caractère spécial"),
        ("Aa1!" + "x" * 69, "au plus 72 caractères"),
        ("Aa1!" + "é" * 40, "72 octets"),
    ],
)
def test_politique_mot_de_passe_refuse(mot_de_passe: str, attendu: str) -> None:
    erreurs = " ".join(erreurs_politique_mot_de_passe(mot_de_passe))
    assert attendu in erreurs


@pytest.mark.parametrize("mot_de_passe", [MOT_DE_PASSE, NOUVEAU_MOT_DE_PASSE, "Aa1!" + "x" * 68])
def test_politique_mot_de_passe_accepte(mot_de_passe: str) -> None:
    assert erreurs_politique_mot_de_passe(mot_de_passe) == []


# ---------------------------------------------------------------------------
# Connexion
# ---------------------------------------------------------------------------


async def test_page_connexion(client: httpx.AsyncClient) -> None:
    reponse = await client.get("/connexion")
    assert reponse.status_code == 200
    page = contenu(reponse)
    assert 'name="csrf_token"' in page
    assert 'type="password"' in page and "data-basculer-mot-de-passe" in page  # œil


async def test_connexion_reussie(client: httpx.AsyncClient, admin: User) -> None:
    reponse = await se_connecter(client, EMAIL_ADMIN)
    assert reponse.status_code == 303
    assert reponse.headers["location"] == "/tableau-de-bord"
    assert "ika_jeton" in client.cookies

    tableau = await client.get("/tableau-de-bord")
    assert tableau.status_code == 200
    assert "Connexion réussie. Bienvenue, Alice Admin !" in contenu(tableau)

    compte = await lire_compte(EMAIL_ADMIN)
    assert compte.derniere_connexion is not None
    connexions = await entrees_historique(ActionHistorique.CONNEXION)
    assert len(connexions) == 1 and connexions[0].utilisateur_id == admin.id


async def test_email_insensible_a_la_casse(client: httpx.AsyncClient, admin: User) -> None:
    reponse = await se_connecter(client, "  ADMIN@IkaDemo.com ")
    assert reponse.status_code == 303


@pytest.mark.parametrize(
    ("suivant", "attendu"),
    [
        ("/utilisateurs", "/utilisateurs"),
        ("//attaquant.example", "/tableau-de-bord"),
        ("https://attaquant.example", "/tableau-de-bord"),
        ("/\\attaquant.example", "/tableau-de-bord"),
    ],
)
async def test_redirection_apres_connexion_securisee(
    client: httpx.AsyncClient, admin: User, suivant: str, attendu: str
) -> None:
    reponse = await se_connecter(client, EMAIL_ADMIN, suivant=suivant)
    assert reponse.headers["location"] == attendu


async def test_connexion_mot_de_passe_incorrect(client: httpx.AsyncClient, admin: User) -> None:
    reponse = await se_connecter(client, EMAIL_ADMIN, "Mauvais#MotDePasse1")
    assert reponse.status_code == 401
    assert MESSAGE_IDENTIFIANTS in contenu(reponse)
    assert "ika_jeton" not in client.cookies
    assert (await lire_compte(EMAIL_ADMIN)).tentatives_echouees == 1
    echecs = await entrees_historique(ActionHistorique.ECHEC_CONNEXION)
    assert len(echecs) == 1 and echecs[0].utilisateur_id == admin.id


async def test_connexion_email_inconnu_meme_message(client: httpx.AsyncClient) -> None:
    reponse = await se_connecter(client, "inconnu@ikademo.com")
    assert reponse.status_code == 401
    assert MESSAGE_IDENTIFIANTS in contenu(reponse)
    echecs = await entrees_historique(ActionHistorique.ECHEC_CONNEXION)
    assert len(echecs) == 1
    assert echecs[0].utilisateur_id is None and echecs[0].utilisateur_email == "inconnu@ikademo.com"


async def test_connexion_formulaire_incomplet(client: httpx.AsyncClient) -> None:
    reponse = await se_connecter(client, "", "")
    assert reponse.status_code == 400
    assert "Veuillez saisir votre adresse e-mail." in contenu(reponse)


async def test_connexion_compte_desactive(client: httpx.AsyncClient, creer_compte) -> None:
    await creer_compte("inactif@ikademo.com", est_actif=False)
    reponse = await se_connecter(client, "inactif@ikademo.com")
    assert reponse.status_code == 401
    assert "Votre compte est désactivé" in contenu(reponse)
    assert "ika_jeton" not in client.cookies


# ---------------------------------------------------------------------------
# Verrouillage du compte
# ---------------------------------------------------------------------------


async def test_verrouillage_apres_cinq_echecs(client: httpx.AsyncClient, admin: User) -> None:
    for numero in range(1, MAX_TENTATIVES_CONNEXION + 1):
        reponse = await se_connecter(client, EMAIL_ADMIN, f"Mauvais#MotDePasse{numero}")
        assert reponse.status_code == 401
    assert "temporairement verrouillé" in contenu(reponse)
    assert f"Réessayez dans {DUREE_VERROUILLAGE_MINUTES} minutes" in contenu(reponse)

    compte = await lire_compte(EMAIL_ADMIN)
    assert compte.est_verrouille
    assert compte.tentatives_echouees == MAX_TENTATIVES_CONNEXION
    assert len(await entrees_historique(ActionHistorique.VERROUILLAGE)) == 1

    # Même avec le bon mot de passe, la connexion est refusée tant que le compte est verrouillé.
    reponse = await se_connecter(client, EMAIL_ADMIN)
    assert reponse.status_code == 401
    assert "temporairement verrouillé" in contenu(reponse)
    assert "ika_jeton" not in client.cookies


async def test_verrouillage_expire(client: httpx.AsyncClient, admin: User) -> None:
    await modifier_compte(
        EMAIL_ADMIN, tentatives_echouees=MAX_TENTATIVES_CONNEXION, verrouille_jusqua=maintenant() - timedelta(minutes=1)
    )
    reponse = await se_connecter(client, EMAIL_ADMIN)
    assert reponse.status_code == 303
    compte = await lire_compte(EMAIL_ADMIN)
    assert compte.tentatives_echouees == 0 and compte.verrouille_jusqua is None


async def test_compteur_remis_a_zero_apres_succes(client: httpx.AsyncClient, admin: User) -> None:
    for _ in range(2):
        await se_connecter(client, EMAIL_ADMIN, "Mauvais#MotDePasse1")
    assert (await lire_compte(EMAIL_ADMIN)).tentatives_echouees == 2
    assert (await se_connecter(client, EMAIL_ADMIN)).status_code == 303
    assert (await lire_compte(EMAIL_ADMIN)).tentatives_echouees == 0


# ---------------------------------------------------------------------------
# Limitation de débit
# ---------------------------------------------------------------------------


async def test_limitation_de_debit_connexion(client: httpx.AsyncClient) -> None:
    for _ in range(10):  # 10 tentatives par e-mail sur 15 minutes
        reponse = await se_connecter(client, "cible@ikademo.com", "Mauvais#MotDePasse1")
        assert reponse.status_code == 401
    reponse = await se_connecter(client, "cible@ikademo.com", "Mauvais#MotDePasse1")
    assert reponse.status_code == 429
    assert int(reponse.headers["Retry-After"]) > 0
    page = contenu(reponse)
    assert "Trop de tentatives" in page and "Vous pourrez réessayer dans environ" in page


# ---------------------------------------------------------------------------
# Session : régénération, déconnexion, révocation
# ---------------------------------------------------------------------------


async def test_session_regeneree_a_la_connexion(client: httpx.AsyncClient, admin: User) -> None:
    csrf_avant = await obtenir_csrf(client, "/connexion")
    session_avant = client.cookies["ika_session"]
    await connecter(client, EMAIL_ADMIN)
    csrf_apres = await obtenir_csrf(client, "/tableau-de-bord")
    assert csrf_apres != csrf_avant
    assert client.cookies["ika_session"] != session_avant


async def test_deconnexion_revoque_le_jeton(client: httpx.AsyncClient, admin: User) -> None:
    await connecter(client, EMAIL_ADMIN)
    ancien_jeton = client.cookies["ika_jeton"]

    reponse = await poster(client, "/deconnexion", page_csrf="/tableau-de-bord")
    assert reponse.status_code == 303 and reponse.headers["location"] == "/connexion"
    assert "ika_jeton" not in client.cookies
    assert "Vous avez été déconnecté avec succès" in contenu(await client.get("/connexion"))

    async with SessionLocal() as db:
        assert await db.scalar(select(JetonRevoque)) is not None
    assert len(await entrees_historique(ActionHistorique.DECONNEXION)) == 1

    # Le JWT révoqué, présenté à nouveau, est refusé.
    async with nouveau_client(cookies={"ika_jeton": ancien_jeton}) as pirate:
        refus = await pirate.get("/tableau-de-bord")
        assert refus.status_code == 303
        assert refus.headers["location"].startswith("/connexion")
        assert "Votre session a expiré ou n'est plus valide" in contenu(await pirate.get("/connexion"))


async def test_deconnexion_uniquement_en_post(client_admin: httpx.AsyncClient) -> None:
    assert (await client_admin.get("/deconnexion")).status_code == 405


async def test_jeton_falsifie_refuse(admin: User) -> None:
    async with nouveau_client(cookies={"ika_jeton": "eyJhbGciOiJIUzI1NiJ9.faux.faux"}) as pirate:
        reponse = await pirate.get("/tableau-de-bord")
        assert reponse.status_code == 303 and reponse.headers["location"].startswith("/connexion")


async def test_page_protegee_redirige_vers_la_connexion(client: httpx.AsyncClient) -> None:
    reponse = await client.get("/utilisateurs?role=ADMIN")
    assert reponse.status_code == 303
    cible = urlparse(reponse.headers["location"])
    assert cible.path == "/connexion"
    assert parse_qs(cible.query)["suivant"] == ["/utilisateurs?role=ADMIN"]
    assert "Veuillez vous connecter pour accéder à cette page." in contenu(await client.get("/connexion"))


async def test_utilisateur_connecte_redirige_depuis_les_pages_publiques(client_admin: httpx.AsyncClient) -> None:
    for chemin in ("/connexion", "/inscription", "/mot-de-passe-oublie"):
        reponse = await client_admin.get(chemin)
        assert reponse.status_code == 303 and reponse.headers["location"] == "/tableau-de-bord"


async def test_compte_desactive_pendant_la_session(client_utilisateur: httpx.AsyncClient) -> None:
    await modifier_compte(EMAIL_UTILISATEUR, est_actif=False)
    reponse = await client_utilisateur.get("/tableau-de-bord")
    assert reponse.status_code == 303
    assert "Votre compte est désactivé" in contenu(await client_utilisateur.get("/connexion"))


# ---------------------------------------------------------------------------
# Inscription
# ---------------------------------------------------------------------------

FORMULAIRE_INSCRIPTION = {
    "nom_complet": "Nina Nouvelle",
    "email": "Nina.Nouvelle@IkaDemo.com",
    "telephone": "+226 70 00 00 00",
    "mot_de_passe": MOT_DE_PASSE,
    "confirmation": MOT_DE_PASSE,
}


async def test_inscription_reussie(client: httpx.AsyncClient) -> None:
    reponse = await poster(client, "/inscription", FORMULAIRE_INSCRIPTION)
    assert reponse.status_code == 303 and reponse.headers["location"] == "/connexion"
    assert "Votre compte a été créé avec succès" in contenu(await client.get("/connexion"))

    compte = await lire_compte("nina.nouvelle@ikademo.com")
    assert compte is not None
    assert compte.email == "nina.nouvelle@ikademo.com"  # stocké en minuscules
    assert compte.role == Role.UTILISATEUR and compte.est_actif
    assert compte.mot_de_passe_hash != MOT_DE_PASSE and verifier_mot_de_passe(MOT_DE_PASSE, compte.mot_de_passe_hash)

    inscriptions = await entrees_historique(ActionHistorique.INSCRIPTION)
    assert len(inscriptions) == 1 and inscriptions[0].donnees_apres["role"] == "UTILISATEUR"

    assert (await se_connecter(client, "nina.nouvelle@ikademo.com")).status_code == 303


async def test_inscription_email_deja_utilise(client: httpx.AsyncClient, utilisateur_simple: User) -> None:
    reponse = await poster(client, "/inscription", {**FORMULAIRE_INSCRIPTION, "email": EMAIL_UTILISATEUR.upper()})
    assert reponse.status_code == 400
    assert "Un compte existe déjà avec cette adresse e-mail." in contenu(reponse)


async def test_inscription_mot_de_passe_faible(client: httpx.AsyncClient) -> None:
    reponse = await poster(
        client, "/inscription", {**FORMULAIRE_INSCRIPTION, "mot_de_passe": "faible", "confirmation": "faible"}
    )
    assert reponse.status_code == 400
    page = contenu(reponse)
    assert "au moins 10 caractères" in page and "majuscule" in page
    assert "Le mot de passe doit respecter les règles suivantes" in page  # règles affichées sous le champ
    assert await lire_compte("nina.nouvelle@ikademo.com") is None


async def test_inscription_confirmation_differente(client: httpx.AsyncClient) -> None:
    reponse = await poster(client, "/inscription", {**FORMULAIRE_INSCRIPTION, "confirmation": "Autre#MotDePasse1"})
    assert reponse.status_code == 400
    assert "La confirmation ne correspond pas au mot de passe saisi." in contenu(reponse)
    assert MOT_DE_PASSE not in reponse.text  # mot de passe jamais réaffiché


async def test_inscription_email_invalide(client: httpx.AsyncClient) -> None:
    reponse = await poster(client, "/inscription", {**FORMULAIRE_INSCRIPTION, "email": "pas-un-email"})
    assert reponse.status_code == 400
    assert "L'adresse e-mail saisie est invalide." in contenu(reponse)


# ---------------------------------------------------------------------------
# Mot de passe oublié et réinitialisation
# ---------------------------------------------------------------------------


@pytest.fixture
def emails_envoyes(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """Capture les e-mails envoyés par le module auth (aucun envoi réel)."""
    envoyes: list[dict[str, str]] = []

    async def faux_envoi(destinataire: str, sujet: str, texte: str, html: str | None = None) -> bool:
        envoyes.append({"destinataire": destinataire, "sujet": sujet, "texte": texte})
        return True

    monkeypatch.setattr("app.auth.services.envoyer_email", faux_envoi)
    return envoyes


def lien_du_mail(texte: str) -> str:
    trouve = re.search(r"http://127\.0\.0\.1:8000(/mot-de-passe/reinitialiser\?jeton=[\w-]+)", texte)
    assert trouve, texte
    return trouve.group(1)


async def demander_lien(client: httpx.AsyncClient, email: str) -> str:
    reponse = await poster(client, "/mot-de-passe-oublie", {"email": email})
    assert reponse.status_code == 303 and reponse.headers["location"] == "/connexion"
    return contenu(await client.get("/connexion"))


async def test_mot_de_passe_oublie_meme_message(
    client: httpx.AsyncClient, utilisateur_simple: User, emails_envoyes: list
) -> None:
    page_existant = await demander_lien(client, EMAIL_UTILISATEUR)
    page_inconnu = await demander_lien(client, "personne@ikademo.com")

    def message(page: str, email: str) -> str:
        trouve = re.search(r'<div class="(?:alerte-texte|notif-texte)">(Si un compte actif.*?)</div>', page, flags=re.S)
        assert trouve
        return trouve.group(1).replace(email, "<email>")

    assert message(page_existant, EMAIL_UTILISATEUR) == message(page_inconnu, "personne@ikademo.com")
    assert [e["destinataire"] for e in emails_envoyes] == [EMAIL_UTILISATEUR]
    assert len(await entrees_historique(ActionHistorique.DEMANDE_REINITIALISATION_MOT_DE_PASSE)) == 1


async def test_reinitialisation_complete(client: httpx.AsyncClient, utilisateur_simple: User, emails_envoyes: list) -> None:
    await demander_lien(client, EMAIL_UTILISATEUR)
    lien = lien_du_mail(emails_envoyes[0]["texte"])
    jeton = parse_qs(urlparse(lien).query)["jeton"][0]

    # Jeton stocké haché (SHA-256), jamais en clair.
    async with SessionLocal() as db:
        enregistrement = await db.scalar(select(JetonReinitialisation))
    assert enregistrement.jeton_hash == hacher_jeton(jeton) and enregistrement.jeton_hash != jeton

    page = await client.get(lien)
    assert page.status_code == 200 and page.headers["Cache-Control"] == "no-store"
    reponse = await client.post(
        "/mot-de-passe/reinitialiser",
        data={
            "csrf_token": extraire_csrf(page.text),
            "jeton": jeton,
            "mot_de_passe": NOUVEAU_MOT_DE_PASSE,
            "confirmation": NOUVEAU_MOT_DE_PASSE,
        },
    )
    assert reponse.status_code == 303 and reponse.headers["location"] == "/connexion"
    assert "Votre mot de passe a été réinitialisé avec succès" in contenu(await client.get("/connexion"))
    assert len(await entrees_historique(ActionHistorique.REINITIALISATION_MOT_DE_PASSE)) == 1

    assert (await se_connecter(client, EMAIL_UTILISATEUR, MOT_DE_PASSE)).status_code == 401
    async with nouveau_client() as autre:
        assert (await se_connecter(autre, EMAIL_UTILISATEUR, NOUVEAU_MOT_DE_PASSE)).status_code == 303

    # Usage unique.
    reutilisation = await client.get(lien)
    assert reutilisation.status_code == 400
    assert "a déjà été utilisé" in contenu(reutilisation)


async def test_reinitialisation_mot_de_passe_faible(
    client: httpx.AsyncClient, utilisateur_simple: User, emails_envoyes: list
) -> None:
    await demander_lien(client, EMAIL_UTILISATEUR)
    lien = lien_du_mail(emails_envoyes[0]["texte"])
    page = await client.get(lien)
    reponse = await client.post(
        "/mot-de-passe/reinitialiser",
        data={
            "csrf_token": extraire_csrf(page.text),
            "jeton": parse_qs(urlparse(lien).query)["jeton"][0],
            "mot_de_passe": "faible",
            "confirmation": "faible",
        },
    )
    assert reponse.status_code == 400
    assert "au moins 10 caractères" in contenu(reponse)


async def test_lien_de_reinitialisation_invalide(client: httpx.AsyncClient) -> None:
    for chemin in ("/mot-de-passe/reinitialiser", "/mot-de-passe/reinitialiser?jeton=inconnu"):
        reponse = await client.get(chemin)
        assert reponse.status_code == 400
        assert "Ce lien de réinitialisation est invalide." in contenu(reponse)


async def test_lien_de_reinitialisation_expire(
    client: httpx.AsyncClient, utilisateur_simple: User, emails_envoyes: list
) -> None:
    await demander_lien(client, EMAIL_UTILISATEUR)
    async with SessionLocal() as db:
        await db.execute(update(JetonReinitialisation).values(expire_le=maintenant() - timedelta(minutes=1)))
        await db.commit()
    reponse = await client.get(lien_du_mail(emails_envoyes[0]["texte"]))
    assert reponse.status_code == 400
    assert "Ce lien de réinitialisation a expiré" in contenu(reponse)


# ---------------------------------------------------------------------------
# Profil
# ---------------------------------------------------------------------------


async def test_modification_du_profil(client_utilisateur: httpx.AsyncClient, utilisateur_simple: User) -> None:
    reponse = await poster(client_utilisateur, "/profil", {"nom_complet": "Ursule Modifiée", "telephone": "70 11 22 33"})
    assert reponse.status_code == 303 and reponse.headers["location"] == "/profil"
    assert "Vos informations ont été mises à jour avec succès." in contenu(await client_utilisateur.get("/profil"))

    compte = await lire_compte(EMAIL_UTILISATEUR)
    assert compte.nom_complet == "Ursule Modifiée" and compte.telephone == "70 11 22 33"
    modification = (await entrees_historique(ActionHistorique.MODIFICATION))[0]
    assert modification.donnees_avant["nom_complet"] == "Ursule Utilisatrice"
    assert modification.donnees_apres["nom_complet"] == "Ursule Modifiée"


async def test_modification_du_profil_invalide(client_utilisateur: httpx.AsyncClient) -> None:
    reponse = await poster(client_utilisateur, "/profil", {"nom_complet": "", "telephone": "abc"})
    assert reponse.status_code == 400
    page = contenu(reponse)
    assert "Ce champ doit contenir au moins 2 caractères." in page and "Numéro de téléphone invalide" in page


async def test_changement_de_mot_de_passe(client_utilisateur: httpx.AsyncClient) -> None:
    donnees = {"nouveau_mot_de_passe": NOUVEAU_MOT_DE_PASSE, "confirmation": NOUVEAU_MOT_DE_PASSE}

    refus = await poster(client_utilisateur, "/profil/mot-de-passe", {"mot_de_passe_actuel": "Faux#MotDePasse1", **donnees})
    assert refus.status_code == 400
    assert "Le mot de passe actuel est incorrect." in contenu(refus)

    reponse = await poster(client_utilisateur, "/profil/mot-de-passe", {"mot_de_passe_actuel": MOT_DE_PASSE, **donnees})
    assert reponse.status_code == 303
    assert "Votre mot de passe a été modifié avec succès." in contenu(await client_utilisateur.get("/profil"))
    assert len(await entrees_historique(ActionHistorique.CHANGEMENT_MOT_DE_PASSE)) == 1
    compte = await lire_compte(EMAIL_UTILISATEUR)
    assert verifier_mot_de_passe(NOUVEAU_MOT_DE_PASSE, compte.mot_de_passe_hash)


async def test_changement_de_mot_de_passe_politique(client_utilisateur: httpx.AsyncClient) -> None:
    reponse = await poster(
        client_utilisateur,
        "/profil/mot-de-passe",
        {"mot_de_passe_actuel": MOT_DE_PASSE, "nouveau_mot_de_passe": "faible", "confirmation": "faible"},
    )
    assert reponse.status_code == 400
    assert "au moins 10 caractères" in contenu(reponse)
