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
    assert "Analyse des caméras" in texte
    assert "Rapport journalier" in texte
    assert "Rapport hebdomadaire" in texte
    assert "Rapport mensuel" in texte
    # Vérification des 4 cartes d'indicateurs globaux
    assert "Total Entrées" in texte
    assert "Passages physiques" in texte
    assert "Total Sorties" in texte
    assert "Départs constatés" in texte
    assert "Clients uniques (IA)" in texte
    assert "Visiteurs réels qualifiés" in texte
    assert "Caméras actives" in texte
    assert "Points de comptage 3D" in texte

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
    if cle_rapport in ["journalier", "hebdomadaire", "mensuel"]:
        assert "Visiteurs boutique" in texte
        assert "Taux d'entrée magasin" in texte
        assert "Courbe comparative d'affluence" in texte
    elif cle_rapport == "flux":
        assert "Taux de capture vitrine" in texte
        assert "Trafic rue" in texte
        assert "Entrées boutique" in texte
    elif cle_rapport == "combinaison":
        assert "Passants devanture (Rue)" in texte
        assert "Entrées réelles boutique" in texte
        assert "Taux de capture vitrine" in texte
    elif cle_rapport == "clients":
        assert "Clients qualifiés (IA)" in texte
        assert "Durée médiane en boutique" in texte
        assert "Journal des sessions" in texte
    elif cle_rapport == "visiteurs":
        assert "Nouveaux visiteurs" in texte
        assert "Visiteurs fidèles (Revisites)" in texte
        assert "Durée moyenne de rétention" in texte
    elif cle_rapport == "employes":
        assert "Passages personnel exclus" in texte
        assert "Impact sur le trafic brut" in texte
        assert "Demi-tours constatés" in texte
    elif cle_rapport == "profil":
        assert "Profils analysés (IA)" in texte
        assert "Hommes" in texte
        assert "Femmes" in texte
    elif cle_rapport in ["entites", "classement"]:
        assert "Palmarès & Classement des caméras" in texte
        assert "Caméras actives / réseau" in texte
    else:
        assert "Total Entrées" in texte
        assert "Clients réels (IA)" in texte

    # Vérification stricte : aucun mot anglais résiduel Foorir
    for terme_anglais in [
        "Store Entry Rate",
        "Avg Stay Time",
        "Total Stay Time",
        "Entity Name",
        "Total Flow",
        "No data",
        "(Male)",
        "(Female)",
    ]:
        assert terme_anglais not in texte, f"Terme anglais '{terme_anglais}' trouvé dans /rapports/{cle_rapport}"

    verifier_sans_inline(reponse.text, f"/rapports/{cle_rapport}")
