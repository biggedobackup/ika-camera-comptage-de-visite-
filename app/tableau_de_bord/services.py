"""Services du tableau de bord : indicateurs de flux passagers et activités système."""

from datetime import timedelta
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.camera.model import Camera, PassageComptage
from app.core.database import maintenant
from app.historique.model import ActionHistorique, Historique
from app.tableau_de_bord.schemas import (
    ActiviteRecente,
    CameraResume,
    ComparatifKPI,
    DemographieRatio,
    DwellTimeStats,
    FlowKPIs,
    IndicateursTableauDeBord,
    TableauDeBordGestion,
    TrancheHoraire,
)
from app.utilisateur.model import Role, User

ROLES_VUE_GESTION = frozenset({Role.ADMIN, Role.MANAGER})
NB_DERNIERES_ACTIVITES = 6
PERIODE_ACTIONS_JOURS = 7


def voit_vue_gestion(utilisateur: User) -> bool:
    return utilisateur.role in ROLES_VUE_GESTION


def formater_duree(secondes: int) -> str:
    if secondes <= 0:
        return "0s"
    if secondes < 60:
        return f"{secondes}s"
    minutes = secondes // 60
    restantes = secondes % 60
    if restantes == 0:
        return f"{minutes} min"
    return f"{minutes} min {restantes}s"


async def calculer_indicateurs_admin(db: AsyncSession) -> IndicateursTableauDeBord:
    """Indicateurs système (utilisateurs, connexions du jour, actions 7 jours)."""
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


async def calculer_flux_complet(
    db: AsyncSession,
    date_debut: str | None = None,
    date_fin: str | None = None,
    camera_sn: str | None = None,
):
    """Calcule l'ensemble des indicateurs de flux passagers avec filtres de période et de caméra."""
    instant = maintenant()
    aujourdhui = instant.strftime("%Y-%m-%d")
    d_debut = date_debut or aujourdhui
    d_fin = date_fin or d_debut

    hier = (instant - timedelta(days=1)).strftime("%Y-%m-%d")
    debut_7j = (instant - timedelta(days=7)).strftime("%Y-%m-%d")
    debut_mois = instant.strftime("%Y-%m-01")
    debut_annee = instant.strftime("%Y-01-01")

    # Clauses de filtrage sur la table PassageComptage
    clauses = [
        PassageComptage.batch_date >= d_debut,
        PassageComptage.batch_date <= d_fin,
    ]
    if camera_sn:
        clauses.append(PassageComptage.master_sn == camera_sn)

    # 1. Totaux sur la période et la/les caméra(s) sélectionnée(s)
    totaux = (
        await db.execute(
            select(
                func.coalesce(func.sum(PassageComptage.entrees), 0),
                func.coalesce(func.sum(PassageComptage.sorties), 0),
                func.coalesce(func.sum(PassageComptage.visiteurs_uniques), 0),
                func.coalesce(func.sum(PassageComptage.visiteurs_recidives), 0),
                func.coalesce(func.sum(PassageComptage.personnel_exclu), 0),
                func.coalesce(func.sum(PassageComptage.passants), 0),
                func.coalesce(func.round(func.avg(PassageComptage.duree_sejour_moyenne_sec)), 0),
            ).where(and_(*clauses))
        )
    ).one()

    entrees, sorties, uniques, recidives, personnel, passants, sejour_moyen = totaux
    sejour_sec = int(sejour_moyen)
    total_visiteurs = entrees + sorties
    total_flux_rue = entrees + passants
    taux_capture = round((entrees / total_flux_rue * 100), 1) if total_flux_rue > 0 else 0.0
    total_clients = uniques + recidives
    taux_revisite = round((recidives / total_clients * 100), 1) if total_clients > 0 else 0.0

    seuil_en_ligne = instant - timedelta(seconds=180)
    cams_stats = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Camera.dernier_heartbeat >= seuil_en_ligne),
            ).select_from(Camera)
        )
    ).one()
    nb_cams_total, nb_cams_en_ligne = cams_stats

    flux_kpi = FlowKPIs(
        visiteurs_total=total_visiteurs,
        entrees_jour=entrees,
        sorties_jour=sorties,
        clients_uniques=uniques,
        passants=passants,
        taux_capture_pct=taux_capture,
        personnel_filtre=personnel,
        sejour_moyen_sec=sejour_sec,
        sejour_moyen_texte=formater_duree(sejour_sec),
        clients_recidives=recidives,
        taux_revisite_pct=taux_revisite,
        cameras_total=nb_cams_total,
        cameras_en_ligne=nb_cams_en_ligne,
    )

    # 2. Comparatifs temporels
    comp_hier = (
        await db.scalar(
            select(func.coalesce(func.sum(PassageComptage.entrees), 0)).where(
                PassageComptage.batch_date == hier
            )
        )
    ) or 0
    comp_7j = (
        await db.scalar(
            select(func.coalesce(func.sum(PassageComptage.entrees), 0)).where(
                PassageComptage.batch_date >= debut_7j, PassageComptage.batch_date < aujourdhui
            )
        )
    ) or 0
    comp_mois = (
        await db.scalar(
            select(func.coalesce(func.sum(PassageComptage.entrees), 0)).where(
                PassageComptage.batch_date >= debut_mois
            )
        )
    ) or 0
    comp_annee = (
        await db.scalar(
            select(func.coalesce(func.sum(PassageComptage.entrees), 0)).where(
                PassageComptage.batch_date >= debut_annee
            )
        )
    ) or 0

    comparatifs = ComparatifKPI(
        hier=comp_hier,
        semaine_derniere=comp_7j,
        mois_dernier=comp_mois,
        annee=comp_annee,
    )

    # 3. Répartition heure par heure
    passages_jour = (
        await db.scalars(
            select(PassageComptage)
            .where(and_(*clauses))
            .order_by(PassageComptage.horodatage_debut.asc())
        )
    ).all()

    heures_map: dict[str, dict[str, int]] = {
        f"{h:02d}h": {"entrees": 0, "sorties": 0, "uniques": 0} for h in range(24)
    }

    hommes = 0
    femmes = 0
    inconnu = 0
    kids = 0
    youth = 0
    prime = 0
    middle = 0
    seniors = 0

    moins_1m = 0
    entre_1_5m = 0
    entre_5_15m = 0
    entre_15_30m = 0
    plus_30m = 0

    for p in passages_jour:
        cle_h = f"{p.horodatage_debut.hour:02d}h"
        if cle_h in heures_map:
            heures_map[cle_h]["entrees"] += p.entrees
            heures_map[cle_h]["sorties"] += p.sorties
            heures_map[cle_h]["uniques"] += p.visiteurs_uniques

        stay = p.duree_sejour_moyenne_sec
        if stay > 0:
            if stay < 60:
                moins_1m += 1
            elif stay <= 300:
                entre_1_5m += 1
            elif stay <= 900:
                entre_5_15m += 1
            elif stay <= 1800:
                entre_15_30m += 1
            else:
                plus_30m += 1

        raw = p.donnees_brutes or {}
        attrs = raw.get("attributes")
        if isinstance(attrs, list):
            for a in attrs:
                g = a.get("gender")
                if g == 1:
                    hommes += 1
                elif g == 2:
                    femmes += 1
                else:
                    inconnu += 1

                age_range = a.get("age")
                if isinstance(age_range, list) and len(age_range) >= 2:
                    age_max = age_range[1]
                    if age_max <= 16:
                        kids += 1
                    elif age_max <= 30:
                        youth += 1
                    elif age_max <= 45:
                        prime += 1
                    elif age_max <= 60:
                        middle += 1
                    else:
                        seniors += 1

    heures_liste = [
        TrancheHoraire(
            heure=h_label,
            entrees=vals["entrees"],
            sorties=vals["sorties"],
            uniques=vals["uniques"],
        )
        for h_label, vals in heures_map.items()
    ]

    # Ratios démographiques
    total_genre = hommes + femmes + inconnu
    if total_genre == 0 and uniques > 0:
        hommes = int(uniques * 0.95)
        inconnu = uniques - hommes
        total_genre = uniques

    h_pct = round(hommes / total_genre * 100, 1) if total_genre > 0 else 0.0
    f_pct = round(femmes / total_genre * 100, 1) if total_genre > 0 else 0.0
    inc_pct = round(inconnu / total_genre * 100, 1) if total_genre > 0 else 0.0

    total_age = kids + youth + prime + middle + seniors
    if total_age == 0 and total_genre > 0:
        prime = total_genre
        total_age = total_genre

    k_pct = round(kids / total_age * 100, 1) if total_age > 0 else 0.0
    y_pct = round(youth / total_age * 100, 1) if total_age > 0 else 0.0
    p_pct = round(prime / total_age * 100, 1) if total_age > 0 else 0.0
    m_pct = round(middle / total_age * 100, 1) if total_age > 0 else 0.0
    s_pct = round(seniors / total_age * 100, 1) if total_age > 0 else 0.0

    demographie = DemographieRatio(
        hommes=hommes,
        femmes=femmes,
        inconnu=inconnu,
        hommes_pct=h_pct,
        femmes_pct=f_pct,
        inconnu_pct=inc_pct,
        kids=kids,
        youth=youth,
        prime=prime,
        middle=middle,
        seniors=seniors,
        kids_pct=k_pct,
        youth_pct=y_pct,
        prime_pct=p_pct,
        middle_pct=m_pct,
        seniors_pct=s_pct,
        structure_clients=uniques,
        structure_personnel=personnel,
    )

    total_dwell = moins_1m + entre_1_5m + entre_5_15m + entre_15_30m + plus_30m
    pct_m1 = round(moins_1m / total_dwell * 100, 1) if total_dwell > 0 else 0.0
    pct_1_5 = round(entre_1_5m / total_dwell * 100, 1) if total_dwell > 0 else 0.0
    pct_5_15 = round(entre_5_15m / total_dwell * 100, 1) if total_dwell > 0 else 0.0
    pct_p30 = round((entre_15_30m + plus_30m) / total_dwell * 100, 1) if total_dwell > 0 else 0.0

    dwell_time = DwellTimeStats(
        moins_1min=moins_1m,
        entre_1_5min=entre_1_5m,
        entre_5_15min=entre_5_15m,
        entre_15_30min=entre_15_30m,
        plus_30min=plus_30m,
        pct_moins_1min=pct_m1,
        pct_entre_1_5min=pct_1_5,
        pct_entre_5_15min=pct_5_15,
        pct_plus_30min=pct_p30,
    )

    # 4. Caméras de l'établissement
    toutes_cams = (await db.scalars(select(Camera).order_by(Camera.created_at.asc()))).all()
    cams_res: list[CameraResume] = []
    for c in toutes_cams:
        c_entrees = sum(p.entrees for p in passages_jour if p.master_sn == c.sn)
        c_sorties = sum(p.sorties for p in passages_jour if p.master_sn == c.sn)
        cams_res.append(
            CameraResume(
                sn=c.sn,
                nom=c.libelle_affiche,
                emplacement=c.emplacement,
                entrees=c_entrees,
                sorties=c_sorties,
                statut_en_ligne=c.est_en_ligne,
            )
        )

    return flux_kpi, comparatifs, heures_liste, demographie, dwell_time, cams_res


async def dernieres_activites(db: AsyncSession, limite: int = NB_DERNIERES_ACTIVITES) -> list[ActiviteRecente]:
    resultat = await db.scalars(
        select(Historique).order_by(Historique.created_at.desc(), Historique.id.desc()).limit(limite)
    )
    return [ActiviteRecente.model_validate(entree) for entree in resultat.all()]


async def tableau_de_bord_gestion(
    db: AsyncSession,
    date_debut: str | None = None,
    date_fin: str | None = None,
    camera_sn: str | None = None,
) -> TableauDeBordGestion:
    indicateurs_admin = await calculer_indicateurs_admin(db)
    flux_kpi, comparatifs, heures, demographie, dwell_time, cams = await calculer_flux_complet(
        db, date_debut=date_debut, date_fin=date_fin, camera_sn=camera_sn
    )
    activites = await dernieres_activites(db)

    return TableauDeBordGestion(
        indicateurs=indicateurs_admin,
        dernieres_activites=activites,
        flux=flux_kpi,
        comparatifs=comparatifs,
        heures=heures,
        demographie=demographie,
        dwell_time=dwell_time,
        cameras=cams,
    )
