"""Pages liste : 20 éléments par page, N° d'ordre continu, total, tri par en-tête et recherche."""

import re
from datetime import timedelta
from html import unescape

import httpx
import pytest

from app.core.database import SessionLocal, maintenant
from app.historique.model import ActionHistorique, Historique
from app.utilisateur.model import Role, User
from conftest import contenu, hash_mot_de_passe_commun, texte_visible

NB_COMPTES = 45  # + l'administrateur connecté = 46 comptes (3 pages)


@pytest.fixture
async def comptes(admin: User) -> list[str]:
    """45 comptes aux noms triables (« Compte 01 » … « Compte 45 »), créés à des dates distinctes."""
    debut = maintenant() - timedelta(days=1)
    noms = [f"Compte {numero:02d}" for numero in range(1, NB_COMPTES + 1)]
    async with SessionLocal() as db:
        db.add_all(
            User(
                nom_complet=nom,
                email=f"compte{numero:02d}@ikademo.com",
                telephone=f"70 00 00 {numero:02d}",
                mot_de_passe_hash=hash_mot_de_passe_commun(),
                role=Role.MANAGER if numero % 3 == 0 else Role.UTILISATEUR,
                est_actif=True,
                created_at=debut + timedelta(minutes=numero),
            )
            for numero, nom in enumerate(noms, start=1)
        )
        await db.commit()
    return noms


def numeros(page: str) -> list[int]:
    return [int(n) for n in re.findall(r'<td class="col-numero">(\d+)</td>', page)]


def noms_affiches(page: str) -> list[str]:
    return [unescape(n) for n in re.findall(r'<a class="fw-medium" href="/utilisateurs/[^"]+">([^<]+)</a>', page)]


async def test_pagination_20_par_page(client_admin: httpx.AsyncClient, comptes: list[str]) -> None:
    reponse1 = await client_admin.get("/utilisateurs")
    assert numeros(reponse1.text) == list(range(1, 21))
    assert "46 éléments au total — 20 par page — page 1/3" in texte_visible(reponse1)

    reponse2 = await client_admin.get("/utilisateurs?page=2")
    assert numeros(reponse2.text) == list(range(21, 41))  # numérotation continue
    assert "46 éléments au total — 20 par page — page 2/3" in texte_visible(reponse2)
    assert 'aria-current="page"><span class="page-link">2</span>' in reponse2.text

    page3 = contenu(await client_admin.get("/utilisateurs?page=3"))
    assert numeros(page3) == list(range(41, 47))

    # Page hors limites ramenée à la dernière ; valeur invalide ramenée à la première.
    assert numeros(contenu(await client_admin.get("/utilisateurs?page=99"))) == list(range(41, 47))
    assert numeros(contenu(await client_admin.get("/utilisateurs?page=abc"))) == list(range(1, 21))


async def test_tri_par_colonne(client_admin: httpx.AsyncClient, comptes: list[str]) -> None:
    croissant = contenu(await client_admin.get("/utilisateurs?tri=nom_complet&ordre=asc"))
    attendus = sorted([*comptes, "Alice Admin"])
    assert noms_affiches(croissant) == attendus[:20]
    # L'en-tête actif propose l'ordre inverse et signale le sens du tri.
    assert 'href="/utilisateurs?tri=nom_complet&ordre=desc"' in croissant
    assert 'aria-sort="ascending"' in croissant

    decroissant = contenu(await client_admin.get("/utilisateurs?tri=nom_complet&ordre=desc"))
    assert noms_affiches(decroissant) == sorted(attendus, reverse=True)[:20]

    # Le tri est conservé dans les liens de pagination.
    assert 'href="/utilisateurs?tri=nom_complet&ordre=desc&page=2"' in decroissant


async def test_tri_hors_liste_blanche_ignore(client_admin: httpx.AsyncClient, comptes: list[str]) -> None:
    reponse = await client_admin.get("/utilisateurs?tri=mot_de_passe_hash&ordre=pirate")
    assert reponse.status_code == 200
    # Tri par défaut : date de création décroissante.
    assert noms_affiches(contenu(reponse))[:2] == ["Alice Admin", "Compte 45"]


async def test_recherche_et_filtres(client_admin: httpx.AsyncClient, comptes: list[str]) -> None:
    reponse = await client_admin.get("/utilisateurs?q=compte1")
    recherche = contenu(reponse)
    assert sorted(noms_affiches(recherche)) == [f"Compte {n}" for n in range(10, 20)]
    assert "10 éléments au total" in texte_visible(reponse)

    assert "15 éléments au total" in texte_visible(await client_admin.get("/utilisateurs?role=MANAGER"))

    vide = await client_admin.get("/utilisateurs?q=introuvable")
    assert "Aucun utilisateur ne correspond à votre recherche" in contenu(vide)
    assert "0 élément au total" in texte_visible(vide)

    # Les filtres actifs sont repris dans les liens d'export.
    assert 'href="/utilisateurs/export/pdf?q=compte1' in recherche


async def test_liste_historique_paginee(client_admin: httpx.AsyncClient, admin: User) -> None:
    async with SessionLocal() as db:
        db.add_all(
            Historique(
                action=ActionHistorique.MODIFICATION,
                module="utilisateur",
                description=f"Entrée {numero:02d}",
                utilisateur_email=admin.email,
                created_at=maintenant() - timedelta(minutes=numero),
            )
            for numero in range(1, 25)
        )
        await db.commit()
    # 24 entrées + la connexion de l'administrateur = 25.
    page1 = await client_admin.get("/historique")
    assert numeros(page1.text) == list(range(1, 21))
    assert "25 éléments au total — 20 par page — page 1/2" in texte_visible(page1)
    page2 = await client_admin.get("/historique?page=2")
    assert numeros(page2.text) == list(range(21, 26))

    tri = contenu(await client_admin.get("/historique?tri=description&ordre=asc&action=MODIFICATION"))
    descriptions = re.findall(r'<td class="cellule-tronquee"[^>]*>(Entrée \d+)</td>', tri)
    assert descriptions == sorted(descriptions) and len(descriptions) == 20
