"""Tests pour la page de documentation interne."""

import httpx
import pytest

from tests.conftest import contenu


async def test_acces_documentation_exige_authentification(client: httpx.AsyncClient) -> None:
    reponse = await client.get("/documentation")
    assert reponse.status_code == 303
    assert "/connexion" in reponse.headers["location"]


async def test_acces_documentation_connecte(client_admin: httpx.AsyncClient) -> None:
    reponse = await client_admin.get("/documentation")
    assert reponse.status_code == 200
    texte = contenu(reponse)
    assert "Documentation" in texte
    assert "Tableau de bord" in texte
    assert "Total comptage" in texte
    assert "Total entrée" in texte
    assert "Total sortie" in texte
    assert "Durée moyen d'une entrée" in texte
    assert "Personnel exclu du comptage" in texte
    assert "Personne passage personne similaire" in texte
    assert "Courbe d'affluence" in texte
    assert "Temps de présence" in texte
    assert "Répartition par genre" in texte
    assert "Tranches d'âge" in texte
    assert "Flux des caméras ( API )" in texte
    assert "Caméras 3D" in texte
    assert "Utilisateurs" in texte
    assert "Historique" in texte
    assert "Mon compte" in texte
    assert "Mon profil" in texte
    assert "Double auth" in texte
