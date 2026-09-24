"""Services du tableau de bord : indicateurs et dernières activités (dates en UTC)."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import maintenant
from app.historique.model import ActionHistorique, Historique
from app.tableau_de_bord.schemas import ActiviteRecente, IndicateursTableauDeBord, TableauDeBordGestion
from app.utilisateur.model import Role, User

# Rôles qui voient les indicateurs et les dernières activités (les autres ont la vue simple).
ROLES_VUE_GESTION = frozenset({Role.ADMIN, Role.MANAGER})

NB_DERNIERES_ACTIVITES = 8
PERIODE_ACTIONS_JOURS = 7


def voit_vue_gestion(utilisateur: User) -> bool:
    return utilisateur.role in ROLES_VUE_GESTION


async def calculer_indicateurs(db: AsyncSession) -> IndicateursTableauDeBord:
    """Utilisateurs (total, actifs, verrouillés), connexions du jour (UTC), actions sur 7 jours glissants."""
    instant = maintenant()
    debut_jour = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    debut_periode = instant - timedelta(days=PERIODE_ACTIONS_JOURS)

    total, actifs, verrouilles = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(User.est_actif.is_(True)),
                func.count().filter(User.verrouille_jusqua > instant),
            ).select_from(User)
        )
    ).one()

    connexions, actions = (
        await db.execute(
            select(
                func.count().filter(
                    Historique.action == ActionHistorique.CONNEXION, Historique.created_at >= debut_jour
                ),
                func.count(),
            )
            .select_from(Historique)
            .where(Historique.created_at >= debut_periode)
        )
    ).one()

    return IndicateursTableauDeBord(
        utilisateurs_total=total,
        utilisateurs_actifs=actifs,
        utilisateurs_verrouilles=verrouilles,
        connexions_du_jour=connexions,
        actions_7_jours=actions,
    )


async def dernieres_activites(db: AsyncSession, limite: int = NB_DERNIERES_ACTIVITES) -> list[ActiviteRecente]:
    resultat = await db.scalars(
        select(Historique).order_by(Historique.created_at.desc(), Historique.id.desc()).limit(limite)
    )
    return [ActiviteRecente.model_validate(entree) for entree in resultat.all()]


async def tableau_de_bord_gestion(db: AsyncSession) -> TableauDeBordGestion:
    return TableauDeBordGestion(
        indicateurs=await calculer_indicateurs(db),
        dernieres_activites=await dernieres_activites(db),
    )
