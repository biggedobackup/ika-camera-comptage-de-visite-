"""Tests pour le portail et les vues analytiques de rapports de flux (style Foorir)."""

import httpx
import pytest

from tests.conftest import contenu
from tests.test_securite import verifier_sans_inline


async def test_acces_portail_rapports_exige_authentification(client: httpx.AsyncClient) -> None:
    reponse = await client.get("/rapports")
    assert reponse.status_code == 303
    assert "/connexion" in reponse.headers["location"]


async def test_acces_portail_rapports_connecte(client_admin: httpx.AsyncClient) -> None:
    reponse = await client_admin.get("/rapports")
    assert reponse.status_code == 200
    texte = contenu(reponse)
    assert "Rapports d'analyse de flux" in texte
    assert "Requête de flux" in texte
    assert "Données horaires" in texte
    assert "Analyse combinée" in texte
    assert "Requête clients" in texte
    assert "Analyse visiteurs" in texte
    assert "Personnel & Employés" in texte
    assert "Profil des clients" in texte
    assert "Analyse des entités" in texte
    assert "Classement des entrées" in texte
    assert "Rapport journalier" in texte
    assert "Rapport hebdomadaire" in texte
    assert "Rapport mensuel" in texte
    # Vérification menu rapports
    assert "data-menu-rapports" in texte
    assert "Tableau de bord" in texte
    assert "Mon profil" in texte
    verifier_sans_inline(reponse.text, "/rapports")


@pytest.mark.parametrize(
    "cle_rapport",
    [
        "flux",
        "horaire",
        "combinaison",
        "clients",
        "visiteurs",
        "employes",
        "entites",
        "classement",
        "journalier",
        "hebdomadaire",
        "mensuel",
        "profil",
    ],
)
async def test_acces_tous_les_rapports_detailles(client_admin: httpx.AsyncClient, cle_rapport: str) -> None:
    reponse = await client_admin.get(f"/rapports/{cle_rapport}")
    assert reponse.status_code == 200
    texte = reponse.text
    assert "data-menu-rapports" in texte
    assert "Total Entrées" in texte
    assert "Clients réels (IA)" in texte
    verifier_sans_inline(texte, f"/rapports/{cle_rapport}")
