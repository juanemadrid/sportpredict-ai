from datetime import datetime, timedelta, timezone
import numpy as np
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import (
    Competition,
    DataSource,
    MarketCatalog,
    Match,
    MatchTeamStat,
    OddsSnapshot,
    PlayerAvailability,
    Team,
)
from app.db.session import Base, engine
from app.ml.odds_math import remove_bookmaker_margin
from app.services.prediction_service import prediction_service


def init_database(db: Session) -> None:
    """Inicializa las tablas, los catálogos de mercados progresivos (Niveles 1-3),
    los proveedores de datos y (solo si SEED_DEMO_DATA=true) el dataset semilla marcado como DEMO.

    En producción el esquema lo gestiona exclusivamente Alembic (`alembic upgrade head`);
    `create_all` solo se usa en desarrollo/pruebas.
    """
    if not settings.is_production:
        Base.metadata.create_all(bind=engine)
    _seed_data_sources(db)
    _seed_market_catalog(db)

    if settings.SEED_DEMO_DATA and db.query(Match).count() == 0:
        _seed_demo_historical_and_upcoming_matches(db)
        prediction_service.train_and_validate_all_models(db, version_tag="v1.0.0-mvp")
        # Generar y bloquear pronósticos pre-partido para los encuentros programados y una muestra reciente
        scheduled = db.query(Match).filter(Match.status == "SCHEDULED").all()
        for m in scheduled:
            prediction_service.analyze_match(db, m.id, persist_prediction=True)
        recent_finished = (
            db.query(Match)
            .filter(Match.status == "FINISHED")
            .order_by(Match.kickoff_utc.desc())
            .limit(12)
            .all()
        )
        for m in reversed(recent_finished):
            prediction_service.analyze_match(db, m.id, persist_prediction=True)


def _seed_data_sources(db: Session) -> None:
    providers = [
        (
            "DEMO_SEED",
            "Dataset Histórico Semilla Verificable (DEMO)",
            "Uso Demostrativo Interno Claramente Identificado",
            99999,
            "ACTIVE",
            True,
        ),
        (
            "AUTHORIZED_CSV",
            "Importador de Archivos CSV Autorizados",
            "Kaggle Open License / Datos Propios Autorizados",
            99999,
            "ACTIVE",
            False,
        ),
        (
            "STATSBOMB_OPEN",
            "StatsBomb Open Data (Investigación)",
            "CC BY-NC-SA 4.0",
            5000,
            "ACTIVE",
            False,
        ),
        (
            "API_FOOTBALL",
            "API-Football v3 (api-sports.io)",
            "Plan Gratuito (100 solicitudes/día)",
            settings.API_FOOTBALL_DAILY_LIMIT,
            "ACTIVE" if settings.is_api_football_configured else "NOT_CONFIGURED",
            False,
        ),
    ]
    for code, name, lic, quota, status, is_demo in providers:
        existing = db.query(DataSource).filter(DataSource.provider_code == code).first()
        if not existing:
            db.add(
                DataSource(
                    provider_code=code,
                    display_name=name,
                    license_type=lic,
                    daily_quota_limit=quota,
                    requests_used_today=0,
                    status=status,
                    is_demo=is_demo,
                )
            )
        else:
            if code == "API_FOOTBALL":
                existing.status = "ACTIVE" if settings.is_api_football_configured else "NOT_CONFIGURED"
    db.commit()


def _seed_market_catalog(db: Session) -> None:
    catalog = [
        ("1X2", "Resultado Final (Victoria Local / Empate / Victoria Visitante)", 1, 50, True, "Nivel 1 activo y evaluado con Poisson, Elo, RF, XGBoost y Ensamble."),
        ("OVER_UNDER_1_5", "Más / Menos de 1.5 Goles", 1, 50, True, "Nivel 1 activo y evaluado mediante distribución de Poisson calibrada."),
        ("OVER_UNDER_2_5", "Más / Menos de 2.5 Goles", 1, 50, True, "Nivel 1 activo y evaluado mediante distribución de Poisson calibrada."),
        ("BTTS", "Ambos Equipos Marcan (Sí / No)", 1, 50, True, "Nivel 1 activo y evaluado mediante matriz conjunta de goles."),
        ("OVER_UNDER_3_5", "Más / Menos de 3.5 Goles", 2, 100, True, "Nivel 2 activo en cola de distribución de goles."),
        ("DOUBLE_CHANCE", "Doble Oportunidad (1X / 12 / X2)", 2, 50, True, "Nivel 2 activo por aditividad de sucesos mutuamente excluyentes."),
        ("EXACT_SCORE", "Marcador Exacto Probable", 2, 120, True, "Nivel 2 activo mediante matriz bivariada Dixon-Coles."),
        ("HALF_TIME_RESULT", "Resultado al Descanso (HT 1X2)", 2, 300, False, "Deshabilitado: requiere >300 partidos con cobertura verificada al descanso."),
        ("CORNERS_OU", "Total de Córners Más / Menos", 3, 500, False, "Nivel 3 bloqueado: requiere serie histórica validada de córners (>500 partidos)."),
        ("CARDS_OU", "Total de Tarjetas Más / Menos", 3, 500, False, "Nivel 3 bloqueado: requiere estadísticas históricas de árbitros y tarjetas (>500 partidos)."),
        ("SHOTS_ON_TARGET", "Tiros a Puerta Más / Menos", 3, 500, False, "Nivel 3 bloqueado: requiere cobertura completa de tiros a puerta por partido."),
    ]
    for code, name, tier, min_s, enabled, reason in catalog:
        if not db.query(MarketCatalog).filter(MarketCatalog.market_code == code).first():
            db.add(
                MarketCatalog(
                    market_code=code,
                    display_name=name,
                    tier_level=tier,
                    min_samples_required=min_s,
                    is_enabled=enabled,
                    status_reason=reason,
                )
            )
    db.commit()


def _seed_demo_historical_and_upcoming_matches(db: Session) -> None:
    """Genera una serie cronológica determinista (semilla fija 42) de partidos históricos
    y próximos encuentros, etiquetados explícitamente con `is_demo=True` y `source_name='DEMO_SEED'`
    (cumpliendo Regla 8: Toda información simulada debe identificarse claramente como DEMO).
    """
    rng = np.random.default_rng(42)

    comp_laliga = Competition(
        code="ESP_LALIGA",
        name="LaLiga EA Sports",
        country="España",
        tier=1,
        has_xg_coverage=True,
        source_name="DEMO_SEED",
        is_demo=True,
    )
    comp_epl = Competition(
        code="ENG_EPL",
        name="Premier League",
        country="Inglaterra",
        tier=1,
        has_xg_coverage=True,
        source_name="DEMO_SEED",
        is_demo=True,
    )
    db.add_all([comp_laliga, comp_epl])
    db.flush()

    laliga_specs = [
        ("Real Madrid", "RMA", 1.55, 0.78),
        ("FC Barcelona", "BAR", 1.52, 0.82),
        ("Atlético de Madrid", "ATM", 1.32, 0.76),
        ("Athletic Club", "ATH", 1.22, 0.90),
        ("Real Sociedad", "RSO", 1.15, 0.92),
        ("Villarreal CF", "VIL", 1.25, 1.08),
        ("Real Betis", "BET", 1.12, 1.05),
        ("Sevilla FC", "SEV", 1.04, 1.15),
        ("Valencia CF", "VAL", 0.98, 1.18),
        ("Girona FC", "GIR", 1.18, 1.12),
    ]
    epl_specs = [
        ("Manchester City", "MCI", 1.60, 0.80),
        ("Arsenal FC", "ARS", 1.50, 0.78),
        ("Liverpool FC", "LIV", 1.54, 0.85),
        ("Chelsea FC", "CHE", 1.28, 1.04),
        ("Aston Villa", "AVL", 1.26, 1.06),
        ("Newcastle United", "NEW", 1.25, 1.05),
        ("Tottenham Hotspur", "TOT", 1.34, 1.16),
        ("Manchester United", "MUN", 1.16, 1.14),
    ]

    laliga_teams = []
    strength_map = {}
    for name, code, att, dfn in laliga_specs:
        t = Team(canonical_name=name, short_code=code, country="España", source_name="DEMO_SEED", is_demo=True)
        db.add(t)
        db.flush()
        laliga_teams.append(t)
        strength_map[t.id] = (att, dfn)

    epl_teams = []
    for name, code, att, dfn in epl_specs:
        t = Team(canonical_name=name, short_code=code, country="Inglaterra", source_name="DEMO_SEED", is_demo=True)
        db.add(t)
        db.flush()
        epl_teams.append(t)
        strength_map[t.id] = (att, dfn)

    now_utc = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start_dt = now_utc - timedelta(days=260)

    match_seq = 1
    # Generar 150 partidos históricos ordenados cronológicamente (dos vueltas simplificadas)
    for round_idx in range(30):
        round_date = start_dt + timedelta(days=round_idx * 8)
        season_str = "2025/2026" if round_idx < 15 else "2026/2027"

        # 3 partidos de LaLiga y 2 de Premier por jornada histórica
        pairs_ll = [
            (laliga_teams[(round_idx + i) % len(laliga_teams)], laliga_teams[(round_idx + i + 1 + (round_idx % 4)) % len(laliga_teams)])
            for i in range(0, 6, 2)
        ]
        pairs_epl = [
            (epl_teams[(round_idx + i) % len(epl_teams)], epl_teams[(round_idx + i + 1 + (round_idx % 3)) % len(epl_teams)])
            for i in range(0, 4, 2)
        ]

        for comp_obj, pairs in [(comp_laliga, pairs_ll), (comp_epl, pairs_epl)]:
            for p_idx, (ht, at) in enumerate(pairs):
                if ht.id == at.id:
                    continue
                kickoff = round_date + timedelta(hours=p_idx * 3)
                att_h, def_h = strength_map[ht.id]
                att_a, def_a = strength_map[at.id]

                true_lam_h = 1.42 * att_h * def_a
                true_lam_a = 1.12 * att_a * def_h
                hg = int(rng.poisson(true_lam_h))
                ag = int(rng.poisson(true_lam_a))
                outcome = "H" if hg > ag else ("A" if ag > hg else "D")

                m = Match(
                    external_ref=f"DEMO-HIST-{match_seq:04d}",
                    competition_id=comp_obj.id,
                    season=season_str,
                    matchday=(round_idx % 15) + 1,
                    kickoff_utc=kickoff,
                    status="FINISHED",
                    home_team_id=ht.id,
                    away_team_id=at.id,
                    home_goals=hg,
                    away_goals=ag,
                    ht_home_goals=min(hg, int(rng.binomial(hg, 0.45))) if hg > 0 else 0,
                    ht_away_goals=min(ag, int(rng.binomial(ag, 0.45))) if ag > 0 else 0,
                    outcome_1x2=outcome,
                    lineups_confirmed=True,
                    source_name="DEMO_SEED",
                    source_license="Uso Demostrativo Interno (DEMO)",
                    captured_at=kickoff - timedelta(hours=2),
                    is_demo=True,
                )
                db.add(m)
                db.flush()

                # Estadísticas del encuentro
                h_xg = round(max(0.15, true_lam_h + float(rng.normal(0, 0.25))), 2)
                a_xg = round(max(0.10, true_lam_a + float(rng.normal(0, 0.25))), 2)
                db.add_all(
                    [
                        MatchTeamStat(
                            match_id=m.id,
                            team_id=ht.id,
                            is_home=True,
                            xg=h_xg,
                            shots=int(max(hg + 3, round(h_xg * 7.5))),
                            shots_on_target=int(max(hg, round(h_xg * 3.2))),
                            corners=int(rng.integers(3, 9)),
                            yellow_cards=int(rng.integers(1, 4)),
                            red_cards=0,
                            possession_pct=round(float(np.clip(50 + (att_h - att_a) * 18, 34, 68)), 1),
                            source_name="DEMO_SEED",
                            is_demo=True,
                        ),
                        MatchTeamStat(
                            match_id=m.id,
                            team_id=at.id,
                            is_home=False,
                            xg=a_xg,
                            shots=int(max(ag + 2, round(a_xg * 7.0))),
                            shots_on_target=int(max(ag, round(a_xg * 3.0))),
                            corners=int(rng.integers(2, 8)),
                            yellow_cards=int(rng.integers(1, 5)),
                            red_cards=0,
                            possession_pct=round(float(100.0 - np.clip(50 + (att_h - att_a) * 18, 34, 68)), 1),
                            source_name="DEMO_SEED",
                            is_demo=True,
                        ),
                    ]
                )

                # Cuotas históricas con margen de casa (~5.2%)
                from scipy.stats import poisson as sp_poisson

                grid = np.outer(sp_poisson.pmf(np.arange(7), true_lam_h), sp_poisson.pmf(np.arange(7), true_lam_a))
                grid /= grid.sum()
                p_h = float(np.sum(np.tril(grid, -1)))
                p_d = float(np.sum(np.diag(grid)))
                p_a = float(np.sum(np.triu(grid, 1)))
                overround = 1.052
                noise_h = float(rng.uniform(0.95, 1.06))
                odds_1x2 = {
                    "HOME": round(max(1.18, 1.0 / max(0.08, p_h * overround * noise_h)), 2),
                    "DRAW": round(max(2.60, 1.0 / max(0.08, p_d * overround)), 2),
                    "AWAY": round(max(1.25, 1.0 / max(0.06, p_a * overround / noise_h)), 2),
                }
                fair_1x2, margin_1x2 = remove_bookmaker_margin(odds_1x2)
                for sel_k, odd_v in odds_1x2.items():
                    db.add(
                        OddsSnapshot(
                            match_id=m.id,
                            bookmaker_name="Referencia Mercado DEMO",
                            market_code="1X2",
                            selection_code=sel_k,
                            decimal_odds=odd_v,
                            implied_prob_raw=round(1.0 / odd_v, 5),
                            overround_margin=margin_1x2,
                            implied_prob_fair=fair_1x2[sel_k],
                            captured_at=kickoff - timedelta(hours=3),
                            source_name="DEMO_SEED",
                            is_demo=True,
                        )
                    )
                match_seq += 1

    # Partidos de HOY y PRÓXIMOS ENCUENTROS (status = SCHEDULED) claramente etiquetados como DEMO
    upcoming_specs = [
        (comp_laliga, laliga_teams[0], laliga_teams[2], now_utc + timedelta(hours=4), "DEMO-TODAY-01", {"HOME": 1.88, "DRAW": 3.55, "AWAY": 4.30}, {"OVER_2_5": 1.92, "UNDER_2_5": 1.90}),
        (comp_epl, epl_teams[1], epl_teams[2], now_utc + timedelta(hours=6), "DEMO-TODAY-02", {"HOME": 2.30, "DRAW": 3.40, "AWAY": 3.10}, {"OVER_2_5": 1.78, "UNDER_2_5": 2.06}),
        (comp_laliga, laliga_teams[1], laliga_teams[3], now_utc + timedelta(hours=8), "DEMO-TODAY-03", {"HOME": 1.62, "DRAW": 4.00, "AWAY": 5.40}, {"OVER_2_5": 1.72, "UNDER_2_5": 2.12}),
        (comp_epl, epl_teams[0], epl_teams[3], now_utc + timedelta(days=1, hours=5), "DEMO-NEXT-01", {"HOME": 1.57, "DRAW": 4.20, "AWAY": 5.75}, {"OVER_2_5": 1.65, "UNDER_2_5": 2.25}),
        (comp_laliga, laliga_teams[4], laliga_teams[5], now_utc + timedelta(days=1, hours=7), "DEMO-NEXT-02", {"HOME": 2.25, "DRAW": 3.30, "AWAY": 3.35}, {"OVER_2_5": 2.02, "UNDER_2_5": 1.82}),
        (comp_epl, epl_teams[4], epl_teams[5], now_utc + timedelta(days=2, hours=6), "DEMO-NEXT-03", {"HOME": 2.40, "DRAW": 3.45, "AWAY": 2.95}, {"OVER_2_5": 1.85, "UNDER_2_5": 1.98}),
    ]

    for comp_obj, ht, at, ko_dt, ref_code, odds_1x2, odds_ou25 in upcoming_specs:
        m = Match(
            external_ref=ref_code,
            competition_id=comp_obj.id,
            season="2026/2027",
            matchday=16,
            kickoff_utc=ko_dt,
            status="SCHEDULED",
            home_team_id=ht.id,
            away_team_id=at.id,
            lineups_confirmed=(ko_dt - now_utc).total_seconds() <= 21600,
            source_name="DEMO_SEED",
            source_license="Uso Demostrativo Interno (DEMO)",
            captured_at=now_utc,
            is_demo=True,
        )
        db.add(m)
        db.flush()

        fair_1x2, margin_1x2 = remove_bookmaker_margin(odds_1x2)
        for sel_k, odd_v in odds_1x2.items():
            db.add(
                OddsSnapshot(
                    match_id=m.id,
                    bookmaker_name="Operador Referencia (DEMO)",
                    market_code="1X2",
                    selection_code=sel_k,
                    decimal_odds=odd_v,
                    implied_prob_raw=round(1.0 / odd_v, 5),
                    overround_margin=margin_1x2,
                    implied_prob_fair=fair_1x2[sel_k],
                    captured_at=now_utc,
                    source_name="DEMO_SEED",
                    is_demo=True,
                )
            )

        fair_ou, margin_ou = remove_bookmaker_margin(odds_ou25)
        for sel_k, odd_v in odds_ou25.items():
            db.add(
                OddsSnapshot(
                    match_id=m.id,
                    bookmaker_name="Operador Referencia (DEMO)",
                    market_code="OVER_UNDER_2_5",
                    selection_code=sel_k,
                    decimal_odds=odd_v,
                    implied_prob_raw=round(1.0 / odd_v, 5),
                    overround_margin=margin_ou,
                    implied_prob_fair=fair_ou[sel_k],
                    captured_at=now_utc,
                    source_name="DEMO_SEED",
                    is_demo=True,
                )
            )

        # Registro de disponibilidad / lesión de ejemplo claramente etiquetado como DEMO
        db.add(
            PlayerAvailability(
                match_id=m.id,
                team_id=at.id,
                player_name=f" Mediocampista Titular ({at.short_code}) [DEMO]",
                status_type="INJURED",
                position="MID",
                impact_note="Baja registrada pre-partido (dato demostrativo etiquetado).",
                source_name="DEMO_SEED",
                recorded_at=now_utc - timedelta(hours=2),
                is_demo=True,
            )
        )

    db.commit()
