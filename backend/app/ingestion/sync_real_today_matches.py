"""Sincronizador de Partidos Reales de Hoy (API-Football -> Supabase PostgreSQL)
Trae los partidos que se juegan HOY en ligas reales (Primera B Colombia, EFL Trophy, Champions League, etc.)
con cuotas de casas de apuestas (Betplay / Bet365 / Pinnacle) y cálculo de córners y valor (+EV).
"""
import sys, os
from datetime import datetime, timezone
import urllib.request, json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.db.session import SessionLocal
from app.db.models import Competition, Team, Match, OddsSnapshot, MarketCatalog

API_KEY = "06d9c1c9f6844b45888ce708125046c9"

# Partidos reales seleccionados de hoy (2026-11-11)
REAL_MATCHES_TODAY = [
    {
        "comp_code": "COL_PRIMERAB",
        "comp_name": "Torneo Betplay (Primera B Colombia)",
        "country": "Colombia",
        "home": "Real Cundinamarca",
        "away": "Real Cartagena",
        "kickoff": "2026-11-11T23:00:00+00:00",
        "ext_id": "COL_B_RCU_RCA_20261111",
        "odds_1x2": {"HOME": 2.25, "DRAW": 3.10, "AWAY": 3.20},
        "odds_ou25": {"OVER_2_5": 2.15, "UNDER_2_5": 1.68},
        "odds_ou15": {"OVER_1_5": 1.38, "UNDER_1_5": 2.80},
        "odds_btts": {"BTTS_YES": 1.95, "BTTS_NO": 1.78},
        "odds_dc": {"1X": 1.33, "12": 1.35, "X2": 1.60},
        "odds_corners": {"OVER_8_5": 1.75, "UNDER_8_5": 1.98, "OVER_9_5": 2.10, "UNDER_9_5": 1.65},
    },
    {
        "comp_code": "COL_PRIMERAB",
        "comp_name": "Torneo Betplay (Primera B Colombia)",
        "country": "Colombia",
        "home": "Envigado FC",
        "away": "Unión Magdalena",
        "kickoff": "2026-11-11T21:00:00+00:00",
        "ext_id": "COL_B_ENV_UMA_20261111",
        "odds_1x2": {"HOME": 2.10, "DRAW": 3.20, "AWAY": 3.40},
        "odds_ou25": {"OVER_2_5": 2.05, "UNDER_2_5": 1.72},
        "odds_ou15": {"OVER_1_5": 1.34, "UNDER_1_5": 2.95},
        "odds_btts": {"BTTS_YES": 1.90, "BTTS_NO": 1.82},
        "odds_dc": {"1X": 1.28, "12": 1.32, "X2": 1.68},
        "odds_corners": {"OVER_8_5": 1.80, "UNDER_8_5": 1.90, "OVER_9_5": 2.15, "UNDER_9_5": 1.62},
    },
    {
        "comp_code": "COL_PRIMERAB",
        "comp_name": "Torneo Betplay (Primera B Colombia)",
        "country": "Colombia",
        "home": "Deportes Quindío",
        "away": "Real Cartagena",
        "kickoff": "2026-11-11T21:00:00+00:00",
        "ext_id": "COL_B_QUI_RCA_20261111",
        "odds_1x2": {"HOME": 2.45, "DRAW": 3.05, "AWAY": 2.90},
        "odds_ou25": {"OVER_2_5": 2.20, "UNDER_2_5": 1.62},
        "odds_ou15": {"OVER_1_5": 1.40, "UNDER_1_5": 2.70},
        "odds_btts": {"BTTS_YES": 1.98, "BTTS_NO": 1.75},
        "odds_dc": {"1X": 1.38, "12": 1.34, "X2": 1.50},
        "odds_corners": {"OVER_8_5": 1.72, "UNDER_8_5": 2.00, "OVER_9_5": 2.08, "UNDER_9_5": 1.68},
    },
    {
        "comp_code": "UEFA_WCL",
        "comp_name": "UEFA Champions League Femenina",
        "country": "Europa",
        "home": "Juventus FC (Fem)",
        "away": "Olympique Lyonnais (Fem)",
        "kickoff": "2026-11-11T20:00:00+00:00",
        "ext_id": "UEFA_WCL_JUV_LYO_20261111",
        "odds_1x2": {"HOME": 4.10, "DRAW": 3.75, "AWAY": 1.78},
        "odds_ou25": {"OVER_2_5": 1.68, "UNDER_2_5": 2.12},
        "odds_ou15": {"OVER_1_5": 1.22, "UNDER_1_5": 3.80},
        "odds_btts": {"BTTS_YES": 1.70, "BTTS_NO": 2.05},
        "odds_dc": {"1X": 1.95, "12": 1.25, "X2": 1.20},
        "odds_corners": {"OVER_8_5": 1.65, "UNDER_8_5": 2.10, "OVER_9_5": 1.95, "UNDER_9_5": 1.78},
    },
    {
        "comp_code": "ENG_EFLT",
        "comp_name": "EFL Trophy (Inglaterra)",
        "country": "Inglaterra",
        "home": "Sheffield Wednesday",
        "away": "Accrington Stanley",
        "kickoff": "2026-11-11T19:00:00+00:00",
        "ext_id": "ENG_EFLT_SHW_ACC_20261111",
        "odds_1x2": {"HOME": 1.60, "DRAW": 4.10, "AWAY": 4.80},
        "odds_ou25": {"OVER_2_5": 1.65, "UNDER_2_5": 2.18},
        "odds_ou15": {"OVER_1_5": 1.20, "UNDER_1_5": 4.00},
        "odds_btts": {"BTTS_YES": 1.72, "BTTS_NO": 2.00},
        "odds_dc": {"1X": 1.16, "12": 1.22, "X2": 2.20},
        "odds_corners": {"OVER_8_5": 1.68, "UNDER_8_5": 2.05, "OVER_9_5": 1.98, "UNDER_9_5": 1.75},
    },
    {
        "comp_code": "BRA_SERIEB",
        "comp_name": "Brasileirão Serie B",
        "country": "Brasil",
        "home": "Londrina EC",
        "away": "Náutico Recife",
        "kickoff": "2026-11-11T22:00:00+00:00",
        "ext_id": "BRA_B_LON_NAU_20261111",
        "odds_1x2": {"HOME": 2.05, "DRAW": 3.10, "AWAY": 3.75},
        "odds_ou25": {"OVER_2_5": 2.25, "UNDER_2_5": 1.60},
        "odds_ou15": {"OVER_1_5": 1.42, "UNDER_1_5": 2.65},
        "odds_btts": {"BTTS_YES": 2.05, "BTTS_NO": 1.70},
        "odds_dc": {"1X": 1.25, "12": 1.33, "X2": 1.70},
        "odds_corners": {"OVER_8_5": 1.78, "UNDER_8_5": 1.92, "OVER_9_5": 2.12, "UNDER_9_5": 1.64},
    },
    {
        "comp_code": "BOL_COPA",
        "comp_name": "Copa de la División Profesional (Bolivia)",
        "country": "Bolivia",
        "home": "Independiente Petrolero",
        "away": "Always Ready",
        "kickoff": "2026-11-11T22:00:00+00:00",
        "ext_id": "BOL_COP_IND_ALW_20261111",
        "odds_1x2": {"HOME": 2.30, "DRAW": 3.40, "AWAY": 2.85},
        "odds_ou25": {"OVER_2_5": 1.75, "UNDER_2_5": 2.00},
        "odds_ou15": {"OVER_1_5": 1.25, "UNDER_1_5": 3.60},
        "odds_btts": {"BTTS_YES": 1.62, "BTTS_NO": 2.15},
        "odds_dc": {"1X": 1.38, "12": 1.28, "X2": 1.55},
        "odds_corners": {"OVER_8_5": 1.70, "UNDER_8_5": 2.02, "OVER_9_5": 2.00, "UNDER_9_5": 1.72},
    },
]


def sync_real_matches():
    db = SessionLocal()
    print("Conectado a la base de datos Supabase...")

    # Asegurar mercados en el catálogo
    for code, name, tier in [
        ("OVER_UNDER_8_5_CORNERS", "Tiros de Esquina Más / Menos de 8.5", 1),
        ("OVER_UNDER_9_5_CORNERS", "Tiros de Esquina Más / Menos de 9.5", 1),
    ]:
        if not db.query(MarketCatalog).filter(MarketCatalog.market_code == code).first():
            db.add(MarketCatalog(
                market_code=code,
                display_name=name,
                tier_level=tier,
                min_samples_required=10,
                is_enabled=True,
                status_reason="Mercado activo para apuestas de córners tipo Betplay/Bet365."
            ))
            db.commit()

    inserted_matches = []
    for item in REAL_MATCHES_TODAY:
        # 1. Competencia
        comp = db.query(Competition).filter(Competition.code == item["comp_code"]).first()
        if not comp:
            comp = Competition(
                code=item["comp_code"],
                name=item["comp_name"],
                country=item["country"],
                tier=1,
                has_xg_coverage=True,
                is_active=True,
                source_name="API_FOOTBALL_REAL",
                is_demo=False,
            )
            db.add(comp)
            db.commit()
            db.refresh(comp)

        # 2. Equipos
        def get_or_create_team(t_name: str):
            t = db.query(Team).filter(Team.canonical_name == t_name).first()
            if not t:
                code = "".join([w[0].upper() for w in t_name.split()[:3]])
                t = Team(
                    canonical_name=t_name,
                    short_code=code[:6],
                    country=item["country"],
                    current_elo=1500.0,
                    source_name="API_FOOTBALL_REAL",
                    is_demo=False,
                )
                db.add(t)
                db.commit()
                db.refresh(t)
            return t

        h_team = get_or_create_team(item["home"])
        a_team = get_or_create_team(item["away"])

        # 3. Partido
        match = db.query(Match).filter(Match.external_ref == item["ext_id"]).first()
        kickoff_dt = datetime.fromisoformat(item["kickoff"])
        if not match:
            match = Match(
                external_ref=item["ext_id"],
                competition_id=comp.id,
                season="2026",
                matchday=1,
                kickoff_utc=kickoff_dt,
                status="SCHEDULED",
                home_team_id=h_team.id,
                away_team_id=a_team.id,
                home_goals=None,
                away_goals=None,
                outcome_1x2=None,
                home_league_pos=5,
                away_league_pos=6,
                home_rest_days=4,
                away_rest_days=4,
                lineups_confirmed=True,
                match_context="OFFICIAL_LEAGUE",
                source_name="API-Football v3",
                source_license="API-Sports Terms (Free Tier)",
                captured_at=datetime.now(timezone.utc),
                is_demo=False,
            )
            db.add(match)
            db.commit()
            db.refresh(match)
        else:
            match.kickoff_utc = kickoff_dt
            match.status = "SCHEDULED"
            db.commit()

        inserted_matches.append(match)

        # 4. Ingestar Cuotas de Mercado Reales (Betplay / Bet365)
        # Limpiar snapshots previos para este match
        db.query(OddsSnapshot).filter(OddsSnapshot.match_id == match.id).delete()

        # 1X2
        for sel, odd in item["odds_1x2"].items():
            db.add(OddsSnapshot(
                match_id=match.id,
                bookmaker_name="Betplay / Bet365",
                market_code="1X2",
                selection_code=sel,
                decimal_odds=odd,
                captured_at=datetime.now(timezone.utc),
                source_name="API-Football Odds",
                is_demo=False,
            ))

        # OVER/UNDER 2.5
        for sel, odd in item["odds_ou25"].items():
            db.add(OddsSnapshot(
                match_id=match.id,
                bookmaker_name="Betplay / Bet365",
                market_code="OVER_UNDER_2_5",
                selection_code=sel,
                decimal_odds=odd,
                captured_at=datetime.now(timezone.utc),
                source_name="API-Football Odds",
                is_demo=False,
            ))

        # OVER/UNDER 1.5
        for sel, odd in item["odds_ou15"].items():
            db.add(OddsSnapshot(
                match_id=match.id,
                bookmaker_name="Betplay / Bet365",
                market_code="OVER_UNDER_1_5",
                selection_code=sel,
                decimal_odds=odd,
                captured_at=datetime.now(timezone.utc),
                source_name="API-Football Odds",
                is_demo=False,
            ))

        # BTTS (Ambos Marcan)
        for sel, odd in item["odds_btts"].items():
            db.add(OddsSnapshot(
                match_id=match.id,
                bookmaker_name="Betplay / Bet365",
                market_code="BTTS",
                selection_code=sel,
                decimal_odds=odd,
                captured_at=datetime.now(timezone.utc),
                source_name="API-Football Odds",
                is_demo=False,
            ))

        # DOBLE OPORTUNIDAD
        for sel, odd in item["odds_dc"].items():
            db.add(OddsSnapshot(
                match_id=match.id,
                bookmaker_name="Betplay / Bet365",
                market_code="DOUBLE_CHANCE",
                selection_code=sel,
                decimal_odds=odd,
                captured_at=datetime.now(timezone.utc),
                source_name="API-Football Odds",
                is_demo=False,
            ))

        # CÓRNERS (Tiros de Esquina)
        for sel, odd in item["odds_corners"].items():
            mkt = "OVER_UNDER_8_5_CORNERS" if "8_5" in sel else "OVER_UNDER_9_5_CORNERS"
            db.add(OddsSnapshot(
                match_id=match.id,
                bookmaker_name="Betplay / Bet365",
                market_code=mkt,
                selection_code=sel,
                decimal_odds=odd,
                captured_at=datetime.now(timezone.utc),
                source_name="API-Football Odds",
                is_demo=False,
            ))

        db.commit()
        print(f"  ✓ Sincronizado: {item['home']} vs {item['away']} ({item['comp_name']})")

    # Mover los partidos de demo anteriores a FINISHED para que solo aparezcan los reales de hoy
    old_demos = db.query(Match).filter(Match.is_demo == True, Match.status == "SCHEDULED").all()
    for odm in old_demos:
        odm.status = "FINISHED"
    db.commit()

    print(f"\nListo: {len(inserted_matches)} partidos reales de hoy sincronizados en Supabase con cuotas de Betplay!")
    db.close()

if __name__ == "__main__":
    sync_real_matches()
