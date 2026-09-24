"""Helpers des pages liste : recherche, filtres, tri en liste blanche, pagination (20) et numéro d'ordre."""

import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import Request
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

TAILLE_PAGE = 20
LONGUEUR_MAX_PARAMETRE = 100

Ordre = Literal["asc", "desc"]


@dataclass(frozen=True)
class ParametresListe:
    """Paramètres de liste lus dans la query string (?q=&tri=&ordre=&page=&<filtres>)."""

    chemin: str
    recherche: str = ""
    tri: str = ""
    ordre: Ordre = "asc"
    page: int = 1
    filtres: dict[str, str] = field(default_factory=dict)

    def query(self, **modifications: Any) -> str:
        """Query string des paramètres actifs, avec modifications (valeur None/"" = paramètre retiré)."""
        valeurs: dict[str, Any] = {"q": self.recherche, **self.filtres, "tri": self.tri, "ordre": self.ordre}
        if self.page > 1:
            valeurs["page"] = self.page
        valeurs.update(modifications)
        return urlencode({k: v for k, v in valeurs.items() if v not in (None, "")})

    def url(self, **modifications: Any) -> str:
        query = self.query(**modifications)
        return f"{self.chemin}?{query}" if query else self.chemin


def lire_parametres_liste(
    request: Request,
    *,
    colonnes_tri: Collection[str],
    tri_defaut: str,
    ordre_defaut: Ordre = "asc",
    filtres: Collection[str] = (),
) -> ParametresListe:
    """Lit et assainit les paramètres de liste. `tri` hors liste blanche → tri par défaut."""
    params = request.query_params

    def texte(nom: str) -> str:
        return (params.get(nom) or "").strip()[:LONGUEUR_MAX_PARAMETRE]

    tri = texte("tri")
    if tri not in colonnes_tri:
        tri = tri_defaut
    ordre = texte("ordre").lower()
    if ordre not in ("asc", "desc"):
        ordre = ordre_defaut
    try:
        page = max(1, int(texte("page") or 1))
    except ValueError:
        page = 1
    return ParametresListe(
        chemin=request.url.path,
        recherche=texte("q"),
        tri=tri,
        ordre=ordre,  # type: ignore[arg-type]
        page=page,
        filtres={nom: valeur for nom in filtres if (valeur := texte(nom))},
    )


def appliquer_recherche(requete: Select, terme: str, colonnes: Sequence[ColumnElement[Any]]) -> Select:
    """Filtre ILIKE '%terme%' (insensible à la casse) sur une ou plusieurs colonnes texte."""
    if not terme:
        return requete
    motif = "%" + terme.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    return requete.where(or_(*(colonne.ilike(motif, escape="\\") for colonne in colonnes)))


def appliquer_tri(
    requete: Select,
    parametres: ParametresListe,
    colonnes_tri: Mapping[str, ColumnElement[Any]],
    departage: ColumnElement[Any] | None = None,
) -> Select:
    """ORDER BY selon la colonne demandée (liste blanche `colonnes_tri`) + colonne de départage stable."""
    colonne = colonnes_tri[parametres.tri]
    ordre = colonne.desc() if parametres.ordre == "desc" else colonne.asc()
    requete = requete.order_by(ordre.nulls_last())
    if departage is not None:
        requete = requete.order_by(departage.desc() if parametres.ordre == "desc" else departage.asc())
    return requete


@dataclass
class PageListe:
    """Une page de résultats + tout ce qu'il faut au template (pagination, tri, numéros, exports)."""

    elements: list[Any]
    total: int
    page: int
    nb_pages: int
    parametres: ParametresListe
    taille_page: int = TAILLE_PAGE

    def numero(self, index: int) -> int:
        """Numéro d'ordre continu entre les pages ; `index` = loop.index (commence à 1)."""
        return (self.page - 1) * self.taille_page + index

    def url_page(self, page: int) -> str:
        return self.parametres.url(page=page if page > 1 else None)

    def url_tri(self, colonne: str) -> str:
        """Clic sur un en-tête : même colonne → inverse l'ordre ; autre colonne → ordre croissant."""
        ordre = "desc" if self.parametres.tri == colonne and self.parametres.ordre == "asc" else "asc"
        return self.parametres.url(tri=colonne, ordre=ordre, page=None)

    def sens_tri(self, colonne: str) -> Ordre | None:
        return self.parametres.ordre if self.parametres.tri == colonne else None

    def url_export(self, chemin_export: str) -> str:
        """URL d'export avec les filtres et le tri actifs (sans pagination)."""
        query = self.parametres.query(page=None)
        return f"{chemin_export}?{query}" if query else chemin_export

    @property
    def pages_visibles(self) -> list[int | None]:
        """Numéros de pages à afficher (None = « … »)."""
        if self.nb_pages <= 7:
            return list(range(1, self.nb_pages + 1))
        pages = sorted({1, 2, self.nb_pages - 1, self.nb_pages, self.page - 1, self.page, self.page + 1})
        resultat: list[int | None] = []
        for numero in (p for p in pages if 1 <= p <= self.nb_pages):
            if resultat and resultat[-1] is not None and numero - resultat[-1] > 1:  # type: ignore[operator]
                resultat.append(None)
            resultat.append(numero)
        return resultat


async def compter(db: AsyncSession, requete: Select) -> int:
    sous_requete = requete.order_by(None).subquery()
    return int(await db.scalar(select(func.count()).select_from(sous_requete)) or 0)


async def paginer(
    db: AsyncSession, requete: Select, parametres: ParametresListe, taille_page: int = TAILLE_PAGE
) -> PageListe:
    """Exécute la requête (déjà filtrée et triée) pour la page demandée (ramenée dans les bornes)."""
    total = await compter(db, requete)
    nb_pages = max(1, math.ceil(total / taille_page))
    page = min(parametres.page, nb_pages)
    resultat = await db.scalars(requete.limit(taille_page).offset((page - 1) * taille_page))
    return PageListe(
        elements=list(resultat.all()),
        total=total,
        page=page,
        nb_pages=nb_pages,
        parametres=parametres,
        taille_page=taille_page,
    )


async def tout_recuperer(db: AsyncSession, requete: Select) -> list[Any]:
    """Toutes les lignes correspondant aux filtres et au tri actifs (exports PDF / Excel)."""
    return list((await db.scalars(requete)).all())


def decrire_filtres(
    parametres: ParametresListe,
    *,
    libelles_filtres: Mapping[str, str] | None = None,
    libelles_tri: Mapping[str, str] | None = None,
    valeurs_filtres: Mapping[str, Mapping[str, str]] | None = None,
) -> list[str]:
    """Lignes lisibles décrivant la recherche, les filtres et le tri (en-tête des exports).

    `valeurs_filtres` permet de traduire une valeur (ex. {"role": {"ADMIN": "Administrateur"}}).
    """
    lignes: list[str] = []
    if parametres.recherche:
        lignes.append(f"Recherche : « {parametres.recherche} »")
    for nom, valeur in parametres.filtres.items():
        libelle = (libelles_filtres or {}).get(nom, nom)
        valeur_lisible = (valeurs_filtres or {}).get(nom, {}).get(valeur, valeur)
        lignes.append(f"{libelle} : {valeur_lisible}")
    if parametres.tri:
        libelle_tri = (libelles_tri or {}).get(parametres.tri, parametres.tri)
        sens = "décroissant" if parametres.ordre == "desc" else "croissant"
        lignes.append(f"Tri : {libelle_tri} ({sens})")
    return lignes
