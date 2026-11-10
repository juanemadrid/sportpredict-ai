"""Servicio de Fase 4: Captura de Cuotas Autorizadas, Comparación Matemática contra el Mercado,
Registro Prospectivo Inmutable Pre-Kickoff, Cálculo de CLV y Evaluación Separada (Histórico vs Prospectivo).

Garantías obligatorias de la Fase 4:
- Utiliza como base estable el motor `v3.1.0` validado sin sobrescribirlo.
- No modifica ni elimina ninguno de los 4,338 partidos históricos reales (`OPENFOOTBALL_CC0`).
- No inventa ni rellena cuotas faltantes.
- Registra predicciones prospectivas únicamente antes de `kickoff_utc` y bloquea cualquier
  edición retroactiva o borrado mediante triggers (SQLite/PostgreSQL, `BEFORE UPDATE` y `BEFORE DELETE`).
- Separa estrictamente resultados históricos (`N = 868` test), prospectivos reales (`is_demo = False`)
  y registros demostrativos (`is_demo = True`).
"""

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import DATA_DIR
from app.db.models import (
    BacktestRun,
    Competition,
    MarketCatalog,
    MarketOddsRecord,
    Match,
    MLModel,
    OddsSnapshot,
    ProspectivePredictionRecord,
    Team,
)
from app.ml.market_comparison import (
    SUPPORTED_PHASE4_MARKETS,
    calculate_closing_line_value,
    calculate_expected_value,
    compare_market_probabilities_and_odds,
    decimal_odds_to_raw_implied_prob,
    normalize_market_margin_power,
    normalize_market_margin_proportional,
    required_prospective_sample_size_for_edge,
)
from app.services.prediction_service import prediction_service
from app.db.triggers import install_prospective_ledger_triggers

_TRIGGERS_INSTALLED_FOR: set = set()


PHASE4_COMPONENT_VERSION = "v4.0.0-market-prospective"
BASE_ML_MODEL_VERSION = "v3.1.0"


ODDS_SOURCES_LICENSING_AUDIT: List[Dict[str, Any]] = [
    {
        "provider_code": "OPENFOOTBALL_CC0",
        "display_name": "OpenFootball Public Domain Archive (openfootball/football.json)",
        "data_type": "Partidos, fechas y marcadores históricos (4,338 partidos reales 2021-22 a 2023-24)",
        "odds_markets_covered": [],
        "line_stages_available": [],
        "license_type": "CC0-1.0 Universal (Dominio Público)",
        "commercial_saas_allowed": True,
        "free_tier_available": True,
        "estimated_monthly_cost_usd": "0 USD (Gratuito y Dominio Público)",
        "status_in_project": "ACTIVO_SOLO_MARCADORES_SIN_CUOTAS",
        "legal_and_technical_notes": (
            "Fuente 100% autorizada para uso comercial SaaS, pero contiene únicamente calendarios y "
            "marcadores reales (HT/FT). No incluye cuotas de casas de apuestas."
        ),
    },
    {
        "provider_code": "FOOTBALL_DATA_CO_UK",
        "display_name": "Football-Data.co.uk Historical CSV Files (Joseph Buchdahl)",
        "data_type": "CSV históricos con cuotas de apertura y cierre (Bet365, Pinnacle, Max, Avg)",
        "odds_markets_covered": ["1X2", "OVER_2_5", "UNDER_2_5"],
        "line_stages_available": ["OPENING", "CLOSING"],
        "license_type": "Propietaria — Uso Personal / Investigación Privada No Comercial",
        "commercial_saas_allowed": False,
        "free_tier_available": True,
        "estimated_monthly_cost_usd": "No publicado (requiere acuerdo comercial expreso para redistribución SaaS)",
        "status_in_project": "BLOQUEADO_POR_LICENCIA_Y_COBERTURA_PARCIAL",
        "legal_and_technical_notes": (
            "1) Sus términos restringen el uso gratuito a investigación privada no comercial. "
            "2) No incluye cuotas para Over 1.5, Over 3.5 ni Ambos Equipos Marcan (BTTS). "
            "No se ingiere automáticamente para proteger la titularidad legal del futuro SaaS."
        ),
    },
    {
        "provider_code": "STATSBOMB_OPEN_DATA",
        "display_name": "StatsBomb Open Data Repository",
        "data_type": "Eventos detallados tiro a tiro (xG) de competiciones seleccionadas",
        "odds_markets_covered": [],
        "line_stages_available": [],
        "license_type": "CC BY-NC-SA 4.0 (No Comercial)",
        "commercial_saas_allowed": False,
        "free_tier_available": True,
        "estimated_monthly_cost_usd": "Licencia comercial empresarial (> 1,000 USD/mes)",
        "status_in_project": "DESCARTADO_NO_COMERCIAL_Y_SIN_CUOTAS",
        "legal_and_technical_notes": (
            "Licencia estrictamente No Comercial (NC) y no contiene cuotas de apuestas."
        ),
    },
    {
        "provider_code": "THE_ODDS_API",
        "display_name": "The Odds API v4 (the-odds-api.com)",
        "data_type": "API REST de cuotas pre-partido en tiempo real e históricas",
        "odds_markets_covered": ["1X2", "OVER_1_5", "OVER_2_5", "UNDER_2_5", "OVER_3_5", "BTTS"],
        "line_stages_available": ["OPENING", "CURRENT", "CLOSING"],
        "license_type": "Comercial por suscripción API (Free Plan limitado a 500 créditos/mes sin histórico)",
        "commercial_saas_allowed": True,
        "free_tier_available": True,
        "estimated_monthly_cost_usd": "0 USD (500 req/mes sin histórico) | 30 USD - 119 USD/mes (planes con histórico y alto volumen)",
        "status_in_project": "CONECTOR_LISTO_REQUIERE_AUTORIZACION_Y_API_KEY",
        "legal_and_technical_notes": (
            "El plan gratuito no incluye cuotas históricas de temporadas pasadas (2021-2024) y requiere "
            "registro de clave API. Siguiendo las reglas de la Fase 4, no se contrata plan pago ni se "
            "introduce clave ficticia."
        ),
    },
    {
        "provider_code": "API_FOOTBALL_V3",
        "display_name": "API-Football v3 (api-sports.io / RapidAPI)",
        "data_type": "API REST de partidos, estadísticas y cuotas pre-partido (ventana móvil de 7 días)",
        "odds_markets_covered": ["1X2", "OVER_1_5", "OVER_2_5", "UNDER_2_5", "OVER_3_5", "BTTS"],
        "line_stages_available": ["OPENING", "CURRENT", "CLOSING"],
        "license_type": "Freemium (100 req/día desarrollo) / Comercial Pro-Ultra-Mega para SaaS",
        "commercial_saas_allowed": True,
        "free_tier_available": True,
        "estimated_monthly_cost_usd": "0 USD (100 req/día desarrollo, sin archivo histórico de cuotas) | 19 USD - 39 USD/mes (planes comerciales)",
        "status_in_project": "CONECTOR_LISTO_REQUIERE_AUTORIZACION_Y_API_KEY",
        "legal_and_technical_notes": (
            "El endpoint `/odds` en plan gratuito sólo conserva una ventana móvil de 7 días y exige "
            "`API_FOOTBALL_KEY` real."
        ),
    },
    {
        "provider_code": "AUTHORIZED_PROSPECTIVE_CAPTURE",
        "display_name": "Captura Prospectiva Verificada / Importador CSV-JSON con Licencia Comercial",
        "data_type": "Registro pre-kickoff de cuotas observadas (inicial, actual, cierre) con sello UTC y licencia verificada",
        "odds_markets_covered": ["1X2", "OVER_1_5", "OVER_2_5", "UNDER_2_5", "OVER_3_5", "BTTS"],
        "line_stages_available": ["OPENING", "CURRENT", "CLOSING"],
        "license_type": "Datos Propios Capturados Prospectivamente / Feed Autorizado por el Usuario",
        "commercial_saas_allowed": True,
        "free_tier_available": True,
        "estimated_monthly_cost_usd": "0 USD (Sin costo externo)",
        "status_in_project": "ACTIVO_Y_OPERATIVO_EN_FASE_4",
        "legal_and_technical_notes": (
            "Permite registrar cuotas reales observadas antes del inicio de cada encuentro (o importar "
            "lotes CSV/JSON cuya licencia comercial esté verificada) con trazabilidad completa de casa "
            "de apuestas, fecha/hora exacta de captura y etapa de línea (inicial, actual, cierre)."
        ),
    },
]


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_prospective_record_sha256(
    match_id: int,
    kickoff_utc_iso: str,
    model_version: str,
    model_code: str,
    market_code: str,
    selection_code: str,
    prob_model: float,
    observed_odds: Optional[float],
    predicted_at_utc_iso: str,
) -> str:
    """Genera el hash SHA-256 inmutable sobre los campos pre-partido de la predicción prospectiva."""
    odds_str = f"{float(observed_odds):.4f}" if observed_odds is not None else "NO_ODDS"
    payload = (
        f"match={match_id}|kickoff={kickoff_utc_iso}|ver={model_version}|mod={model_code}|"
        f"mkt={market_code}|sel={selection_code}|prob={prob_model:.6f}|odds={odds_str}|"
        f"pred_at={predicted_at_utc_iso}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Phase4MarketAndProspectiveService:
    """Servicio de Fase 4 para captura autorizada de cuotas, comparación matemática,
    registro prospectivo inmutable y evaluación separada (histórica vs prospectiva).
    """

    def ensure_phase4_tables_and_triggers(self, db: Session) -> None:
        """Crea las tablas de Fase 4 (si no existen) e instala los triggers SQLite que impiden
        cualquier modificación retroactiva de los campos pre-partido o eliminación de registros
        en `prospective_predictions`. También asegura que `UNDER_2_5` esté en `market_catalog`.
        """
        bind = db.get_bind()
        MarketOddsRecord.__table__.create(bind=bind, checkfirst=True)
        ProspectivePredictionRecord.__table__.create(bind=bind, checkfirst=True)

        # Asegurar presencia de códigos de mercado normalizados en market_catalog
        for m_code, m_info in [
            ("OVER_1_5", ("Más de 1.5 Goles (Over 1.5)", 1, "Habilitado en Fase 3/4 con modelo principal Poisson/Dixon-Coles v3.1.0.")),
            ("OVER_2_5", ("Más de 2.5 Goles (Over 2.5)", 1, "Habilitado en Fase 3/4 con modelo principal Poisson/Dixon-Coles v3.1.0.")),
            ("UNDER_2_5", ("Menos de 2.5 Goles (Under 2.5)", 1, "Habilitado en Fase 3/4 con modelo principal Poisson/Dixon-Coles v3.1.0.")),
            ("OVER_3_5", ("Más de 3.5 Goles (Over 3.5)", 2, "Habilitado en Fase 3/4 con modelo principal Poisson/Dixon-Coles v3.1.0.")),
        ]:
            existing_cat = db.query(MarketCatalog).filter(MarketCatalog.market_code == m_code).first()
            if not existing_cat:
                db.add(
                    MarketCatalog(
                        market_code=m_code,
                        display_name=m_info[0],
                        tier_level=m_info[1],
                        min_samples_required=50,
                        is_enabled=True,
                        status_reason=m_info[2],
                    )
                )
        db.commit()

        # Instalar triggers de inmutabilidad (SQLite o PostgreSQL) una sola vez por motor/proceso.
        engine_key = str(bind.url) if hasattr(bind, "url") else repr(bind)
        if engine_key not in _TRIGGERS_INSTALLED_FOR:
            install_prospective_ledger_triggers(db.connection())
            db.commit()
            _TRIGGERS_INSTALLED_FOR.add(engine_key)

    def get_odds_sources_and_licensing_catalog(self) -> Dict[str, Any]:
        """Devuelve el catálogo auditado de fuentes de cuotas, sus licencias, cobertura de mercados
        y costos potenciales (Secciones 1, 2 y 8 del informe de Fase 4).
        """
        return {
            "phase": "FASE_4_MARKET_ODDS_AND_PROSPECTIVE_VALIDATION",
            "component_version": PHASE4_COMPONENT_VERSION,
            "base_ml_version": BASE_ML_MODEL_VERSION,
            "policy_summary": (
                "No se inventan ni completan cuotas faltantes sobre los 4,338 partidos históricos reales "
                "(OPENFOOTBALL_CC0 carece de cuotas). Las fuentes gratuitas con cuotas históricas en CSV "
                "(como Football-Data.co.uk) tienen restricción de uso personal no comercial y no cubren "
                "Over 1.5, Over 3.5 ni BTTS. Por ello, se documentan todas las alternativas y costos "
                "potenciales sin contratar servicios pagos."
            ),
            "sources": ODDS_SOURCES_LICENSING_AUDIT,
        }

    def capture_market_odds(
        self,
        db: Session,
        match_id: int,
        market_code: str,
        bookmaker_name: str,
        provider_source: str,
        license_type: str,
        commercial_saas_allowed: bool,
        odds_by_selection: Dict[str, float],
        line_stage: str = "CURRENT",
        captured_at_utc: Optional[datetime] = None,
        is_demo: bool = False,
    ) -> Dict[str, Any]:
        """Captura cuotas reales para un mercado soportado (1X2, OVER_1_5, OVER_2_5, UNDER_2_5,
        OVER_3_5, BTTS) validando:
        1. Que el mercado exista en SUPPORTED_PHASE4_MARKETS.
        2. Que la licencia permita uso comercial SaaS (salvo que `is_demo=True`).
        3. Que `captured_at_utc < match.kickoff_utc` para capturas pre-partido.
        4. Que todas las cuotas suministradas sean > 1.0 (sin inventar cuotas omitidas).
        """
        self.ensure_phase4_tables_and_triggers(db)

        if market_code not in SUPPORTED_PHASE4_MARKETS:
            raise ValueError(
                f"Mercado '{market_code}' no soportado en Fase 4. Soportados: {list(SUPPORTED_PHASE4_MARKETS.keys())}"
            )

        if not commercial_saas_allowed and not is_demo:
            raise ValueError(
                f"LICENSE_RESTRICTION_ERROR: La fuente '{provider_source}' ({license_type}) no autoriza "
                "uso comercial en SaaS. Deteniendo ingesta según reglas de Fase 4."
            )

        stage = line_stage.upper().strip()
        if stage not in ("OPENING", "CURRENT", "CLOSING"):
            raise ValueError(f"line_stage debe ser OPENING, CURRENT o CLOSING; recibido: {line_stage}")

        match = db.query(Match).filter(Match.id == match_id).first()
        if not match:
            raise ValueError(f"Partido con ID {match_id} no encontrado.")

        now_utc = _ensure_utc(captured_at_utc or datetime.now(timezone.utc))
        kickoff_utc = _ensure_utc(match.kickoff_utc)

        if now_utc >= kickoff_utc:
            raise ValueError(
                f"PRE_KICKOFF_ODDS_VIOLATION: La captura de cuotas pre-partido ({now_utc.isoformat()}) "
                f"debe ser estrictamente anterior al inicio del partido ({kickoff_utc.isoformat()})."
            )

        expected_sels = SUPPORTED_PHASE4_MARKETS[market_code]["selections"]
        raw_probs, fair_prop, overround = normalize_market_margin_proportional(
            odds_by_selection, expected_selections=expected_sels
        )
        fair_power = normalize_market_margin_power(
            odds_by_selection, expected_selections=expected_sels
        )

        saved_rows = []
        for sel_code, odd_val in odds_by_selection.items():
            if odd_val is None:
                continue
            if sel_code not in expected_sels:
                raise ValueError(
                    f"Selección '{sel_code}' inválida para mercado '{market_code}'. Esperadas: {expected_sels}"
                )
            odd_f = float(odd_val)
            rec = (
                db.query(MarketOddsRecord)
                .filter(
                    MarketOddsRecord.match_id == match_id,
                    MarketOddsRecord.bookmaker_name == bookmaker_name,
                    MarketOddsRecord.market_code == market_code,
                    MarketOddsRecord.selection_code == sel_code,
                )
                .first()
            )
            if not rec:
                rec = MarketOddsRecord(
                    match_id=match_id,
                    bookmaker_name=bookmaker_name,
                    provider_source=provider_source,
                    license_type=license_type,
                    commercial_saas_allowed=commercial_saas_allowed,
                    market_code=market_code,
                    selection_code=sel_code,
                    captured_at=now_utc,
                    is_demo=is_demo,
                )
                db.add(rec)

            if stage == "OPENING":
                rec.opening_odds = odd_f
                rec.opening_captured_at = now_utc
                if rec.current_odds is None:
                    rec.current_odds = odd_f
                    rec.current_captured_at = now_utc
            elif stage == "CURRENT":
                rec.current_odds = odd_f
                rec.current_captured_at = now_utc
            elif stage == "CLOSING":
                rec.closing_odds = odd_f
                rec.closing_captured_at = now_utc
                if rec.current_odds is None:
                    rec.current_odds = odd_f
                    rec.current_captured_at = now_utc

            rec.implied_prob_raw = raw_probs.get(sel_code)
            rec.bookmaker_overround = overround
            rec.implied_prob_fair_prop = fair_prop.get(sel_code)
            rec.implied_prob_fair_power = fair_power.get(sel_code)
            rec.captured_at = now_utc
            saved_rows.append(sel_code)

        db.commit()

        # Si el envío fue de cuotas de cierre (CLOSING), actualizar CLV en predicciones prospectivas existentes
        if stage == "CLOSING":
            self._refresh_clv_on_prospective_records(
                db=db,
                match_id=match_id,
                market_code=market_code,
                closing_odds_by_selection=odds_by_selection,
                closing_fair_probs=fair_prop,
            )

        return {
            "match_id": match_id,
            "market_code": market_code,
            "bookmaker_name": bookmaker_name,
            "provider_source": provider_source,
            "license_type": license_type,
            "line_stage": stage,
            "captured_at_utc": now_utc.isoformat(),
            "overround_margin": overround,
            "selections_saved": saved_rows,
            "implied_prob_fair_proportional": fair_prop,
            "implied_prob_fair_power": fair_power,
        }

    def _refresh_clv_on_prospective_records(
        self,
        db: Session,
        match_id: int,
        market_code: str,
        closing_odds_by_selection: Dict[str, float],
        closing_fair_probs: Dict[str, float],
    ) -> None:
        rows = (
            db.query(ProspectivePredictionRecord)
            .filter(
                ProspectivePredictionRecord.match_id == match_id,
                ProspectivePredictionRecord.market_code == market_code,
            )
            .all()
        )
        for r in rows:
            c_odd = closing_odds_by_selection.get(r.selection_code)
            if c_odd is not None and float(c_odd) > 1.0:
                r.closing_odds = float(c_odd)
                clv_o, clv_f = calculate_closing_line_value(
                    observed_odds=r.observed_odds,
                    closing_odds=float(c_odd),
                    closing_fair_prob=closing_fair_probs.get(r.selection_code),
                )
                r.clv_odds_pct = clv_o
                r.clv_fair_prob_pct = clv_f
        db.commit()

    def compute_match_phase4_valuation(
        self,
        db: Session,
        match_id: int,
    ) -> Dict[str, Any]:
        """Calcula para un partido las probabilidades de los 6 mercados de Fase 4 usando la versión
        estable `v3.1.0` (`ENSEMBLE` en `1X2` y `POISSON` en `OVER_1_5`, `OVER_2_5`, `UNDER_2_5`,
        `OVER_3_5`, `BTTS`), y las contrasta contra las cuotas reales registradas en `market_odds_records`
        (o en `odds_snapshots` si existen), sin inventar cuotas faltantes.
        """
        self.ensure_phase4_tables_and_triggers(db)

        base_analysis = prediction_service.analyze_match(db, match_id=match_id, persist_prediction=False)
        match_info = base_analysis["match"]
        model_version = base_analysis["model_version"]
        models_1x2 = base_analysis["models_comparison_1x2"]

        # Extraer probabilidades por mercado según la selección científica de v3.1.0
        m_ou15 = base_analysis["markets"]["OVER_UNDER_1_5"]["selections"]
        m_ou25 = base_analysis["markets"]["OVER_UNDER_2_5"]["selections"]
        m_ou35 = base_analysis["markets"]["OVER_UNDER_3_5"]["selections"]
        m_btts = base_analysis["markets"]["BTTS"]["selections"]

        p_over15 = float((m_ou15.get("OVER") or m_ou15.get("OVER_1_5") or {})["prob_estimated"])
        p_under15 = float((m_ou15.get("UNDER") or m_ou15.get("UNDER_1_5") or {})["prob_estimated"])

        p_over25 = float((m_ou25.get("OVER") or m_ou25.get("OVER_2_5") or {})["prob_estimated"])
        p_under25 = float((m_ou25.get("UNDER") or m_ou25.get("UNDER_2_5") or {})["prob_estimated"])

        p_over35 = float((m_ou35.get("OVER") or m_ou35.get("OVER_3_5") or {})["prob_estimated"])
        p_under35 = float((m_ou35.get("UNDER") or m_ou35.get("UNDER_3_5") or {})["prob_estimated"])

        p_btts_yes = float((m_btts.get("YES") or m_btts.get("BTTS_YES") or {})["prob_estimated"])
        p_btts_no = float((m_btts.get("NO") or m_btts.get("BTTS_NO") or {})["prob_estimated"])

        # Normalizar estructura de diccionarios de mercados de goles
        normalized_probs: Dict[str, Dict[str, float]] = {
            "1X2": {
                "HOME": float(models_1x2["ENSEMBLE"]["HOME"]),
                "DRAW": float(models_1x2["ENSEMBLE"]["DRAW"]),
                "AWAY": float(models_1x2["ENSEMBLE"]["AWAY"]),
            },
            "OVER_1_5": {
                "OVER": p_over15,
                "UNDER": p_under15,
            },
            "OVER_2_5": {
                "OVER": p_over25,
                "UNDER": p_under25,
            },
            "UNDER_2_5": {
                "UNDER": p_under25,
                "OVER": p_over25,
            },
            "OVER_3_5": {
                "OVER": p_over35,
                "UNDER": p_under35,
            },
            "BTTS": {
                "YES": p_btts_yes,
                "NO": p_btts_no,
            },
        }

        per_model_1x2 = {
            sel: [float(models_1x2[m][sel]) for m in ("POISSON", "ELO", "RANDOM_FOREST", "XGBOOST")]
            for sel in ("HOME", "DRAW", "AWAY")
        }

        # Consultar cuotas registradas en `market_odds_records` (Fase 4)
        p4_odds_rows = (
            db.query(MarketOddsRecord)
            .filter(MarketOddsRecord.match_id == match_id)
            .order_by(MarketOddsRecord.captured_at.desc())
            .all()
        )
        opening_map: Dict[str, Dict[str, Optional[float]]] = {}
        current_map: Dict[str, Dict[str, Optional[float]]] = {}
        closing_map: Dict[str, Dict[str, Optional[float]]] = {}
        bm_by_market: Dict[str, str] = {}
        cap_by_market: Dict[str, str] = {}

        for r in p4_odds_rows:
            opening_map.setdefault(r.market_code, {})[r.selection_code] = r.opening_odds
            current_map.setdefault(r.market_code, {})[r.selection_code] = r.current_odds
            closing_map.setdefault(r.market_code, {})[r.selection_code] = r.closing_odds
            bm_by_market[r.market_code] = r.bookmaker_name
            cap_by_market[r.market_code] = _ensure_utc(r.captured_at).isoformat()

        # Si `OVER_2_5` tiene cuotas en `market_odds_records` y `UNDER_2_5` no se cargó por separado, compartir las ramas
        if "OVER_2_5" in current_map and "UNDER_2_5" not in current_map:
            opening_map["UNDER_2_5"] = dict(opening_map.get("OVER_2_5", {}))
            current_map["UNDER_2_5"] = dict(current_map.get("OVER_2_5", {}))
            closing_map["UNDER_2_5"] = dict(closing_map.get("OVER_2_5", {}))
            bm_by_market["UNDER_2_5"] = bm_by_market.get("OVER_2_5", "")
            cap_by_market["UNDER_2_5"] = cap_by_market.get("OVER_2_5", "")

        # Fallback de lectura sobre `odds_snapshots` existentes si no hay en `market_odds_records`
        legacy_odds = db.query(OddsSnapshot).filter(OddsSnapshot.match_id == match_id).all()
        legacy_code_alias = {
            "1X2": "1X2",
            "OVER_UNDER_1_5": "OVER_1_5",
            "OVER_UNDER_2_5": "OVER_2_5",
            "OVER_UNDER_3_5": "OVER_3_5",
            "BTTS": "BTTS",
        }
        for lo in legacy_odds:
            mapped_mkt = legacy_code_alias.get(lo.market_code, lo.market_code)
            if mapped_mkt not in current_map or lo.selection_code not in current_map[mapped_mkt]:
                current_map.setdefault(mapped_mkt, {})[lo.selection_code] = lo.decimal_odds
                bm_by_market.setdefault(mapped_mkt, lo.bookmaker_name)
                if lo.captured_at:
                    cap_by_market.setdefault(mapped_mkt, _ensure_utc(lo.captured_at).isoformat())
            if mapped_mkt == "OVER_2_5":
                current_map.setdefault("UNDER_2_5", {})[lo.selection_code] = lo.decimal_odds
                bm_by_market.setdefault("UNDER_2_5", lo.bookmaker_name)
                if lo.captured_at:
                    cap_by_market.setdefault("UNDER_2_5", _ensure_utc(lo.captured_at).isoformat())

        markets_comparison: Dict[str, Any] = {}
        markets_without_statistical_edge: List[str] = []
        candidate_value_selections: List[Dict[str, Any]] = []

        for mkt_code, meta in SUPPORTED_PHASE4_MARKETS.items():
            primary_mod = meta["primary_model_v3_1"]
            comp_res = compare_market_probabilities_and_odds(
                market_code=mkt_code,
                model_version=model_version,
                model_code=primary_mod,
                probs_by_selection=normalized_probs[mkt_code],
                current_odds_by_selection=current_map.get(mkt_code),
                opening_odds_by_selection=opening_map.get(mkt_code),
                closing_odds_by_selection=closing_map.get(mkt_code),
                per_model_probs_by_selection=per_model_1x2 if mkt_code == "1X2" else None,
                bookmaker_name=bm_by_market.get(mkt_code),
                captured_at_utc=cap_by_market.get(mkt_code),
            )
            sel_dicts = {s: obj.to_dict() for s, obj in comp_res.items()}
            has_any_candidate = any(
                v["edge_classification"] == "CANDIDATE_STATISTICAL_EDGE" for v in sel_dicts.values()
            )
            if not has_any_candidate:
                markets_without_statistical_edge.append(mkt_code)

            for s_code, s_val in sel_dicts.items():
                if s_val["edge_classification"] == "CANDIDATE_STATISTICAL_EDGE":
                    candidate_value_selections.append(
                        {
                            "market_code": mkt_code,
                            "selection_code": s_code,
                            "prob_model": s_val["prob_model"],
                            "current_odds": s_val["current_odds"],
                            "implied_prob_fair": s_val["implied_prob_fair_proportional"],
                            "prob_diff": s_val["prob_diff_vs_market_prop"],
                            "expected_value": s_val["expected_value"],
                            "edge_z_score": s_val["edge_z_score"],
                        }
                    )

            markets_comparison[mkt_code] = {
                "market_code": mkt_code,
                "display_name": meta["display_name"],
                "primary_model_code": primary_mod,
                "model_version": model_version,
                "has_statistical_edge_candidate": has_any_candidate,
                "bookmaker_name": bm_by_market.get(mkt_code),
                "odds_captured_at_utc": cap_by_market.get(mkt_code),
                "selections": sel_dicts,
            }

        return {
            "match": match_info,
            "model_version": model_version,
            "phase4_component_version": PHASE4_COMPONENT_VERSION,
            "markets_comparison": markets_comparison,
            "markets_without_statistical_edge": markets_without_statistical_edge,
            "candidate_statistical_edges": candidate_value_selections,
            "scientific_disclaimer": (
                "Una diferencia entre la probabilidad estimada por el modelo y la probabilidad implícita "
                "del mercado (o un EV > 0 puntual) NO constituye una ventaja rentable demostrada hasta ser "
                "verificada en una muestra prospectiva suficientemente amplia."
            ),
        }

    def register_prospective_predictions_for_match(
        self,
        db: Session,
        match_id: int,
        markets_to_register: Optional[List[str]] = None,
        predicted_at_override_utc: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Registra en `prospective_predictions` las predicciones de los mercados indicados (por defecto
        los 6 mercados de Fase 4) verificando estrictamente:
        1. `predicted_at_utc < match.kickoff_utc` (Requisito obligatorio pre-kickoff).
        2. `match.status == 'SCHEDULED'` (Prohibido registrar prospectivamente partidos ya iniciados o finalizados).
        3. Si una predicción ya fue registrada antes del inicio para `(match_id, model_version, market_code, selection_code)`,
           es inmutable y se devuelve intacta sin sobrescribirla.
        """
        self.ensure_phase4_tables_and_triggers(db)

        match = db.query(Match).filter(Match.id == match_id).first()
        if not match:
            raise ValueError(f"Partido con ID {match_id} no encontrado.")

        now_utc = _ensure_utc(predicted_at_override_utc or datetime.now(timezone.utc))
        kickoff_utc = _ensure_utc(match.kickoff_utc)

        if match.status != "SCHEDULED" or now_utc >= kickoff_utc:
            raise ValueError(
                f"PRE_KICKOFF_VIOLATION: El registro prospectivo exige que el partido esté programado "
                f"(status='{match.status}') y que la hora de generación ({now_utc.isoformat()}) sea "
                f"estrictamente anterior al kickoff ({kickoff_utc.isoformat()})."
            )

        valuation = self.compute_match_phase4_valuation(db, match_id=match_id)
        m_info = valuation["match"]
        model_version = valuation["model_version"]
        fixture_label = f"{m_info['home_team']['name']} vs {m_info['away_team']['name']}"
        target_markets = markets_to_register or list(SUPPORTED_PHASE4_MARKETS.keys())

        created_count = 0
        existing_count = 0
        records_out = []

        for mkt_code in target_markets:
            if mkt_code not in valuation["markets_comparison"]:
                continue
            mkt_block = valuation["markets_comparison"][mkt_code]
            mod_code = mkt_block["primary_model_code"]

            for sel_code, sel_data in mkt_block["selections"].items():
                existing = (
                    db.query(ProspectivePredictionRecord)
                    .filter(
                        ProspectivePredictionRecord.match_id == match_id,
                        ProspectivePredictionRecord.model_version == model_version,
                        ProspectivePredictionRecord.market_code == mkt_code,
                        ProspectivePredictionRecord.selection_code == sel_code,
                    )
                    .first()
                )
                if existing:
                    existing_count += 1
                    records_out.append(self._serialize_prospective_record(existing))
                    continue

                cap_dt = (
                    datetime.fromisoformat(sel_data["captured_at_utc"])
                    if sel_data.get("captured_at_utc")
                    else None
                )
                rec_hash = compute_prospective_record_sha256(
                    match_id=match_id,
                    kickoff_utc_iso=kickoff_utc.isoformat(),
                    model_version=model_version,
                    model_code=mod_code,
                    market_code=mkt_code,
                    selection_code=sel_code,
                    prob_model=float(sel_data["prob_model"]),
                    observed_odds=sel_data.get("current_odds"),
                    predicted_at_utc_iso=now_utc.isoformat(),
                )

                new_rec = ProspectivePredictionRecord(
                    match_id=match_id,
                    competition_id=match.competition_id,
                    competition_name=m_info["competition_name"],
                    fixture_label=fixture_label,
                    kickoff_utc=kickoff_utc,
                    model_version=model_version,
                    model_code=mod_code,
                    market_code=mkt_code,
                    selection_code=sel_code,
                    prob_model=float(sel_data["prob_model"]),
                    fair_model_odds=float(sel_data["fair_model_odds"]),
                    bookmaker_name=sel_data.get("bookmaker_name"),
                    opening_odds=sel_data.get("opening_odds"),
                    observed_odds=sel_data.get("current_odds"),
                    closing_odds=sel_data.get("closing_odds"),
                    implied_prob_raw=sel_data.get("implied_prob_raw"),
                    bookmaker_overround=sel_data.get("bookmaker_overround"),
                    implied_prob_fair=sel_data.get("implied_prob_fair_proportional"),
                    implied_prob_fair_power=sel_data.get("implied_prob_fair_power"),
                    prob_edge=sel_data.get("prob_diff_vs_market_prop"),
                    expected_value=sel_data.get("expected_value"),
                    edge_z_score=sel_data.get("edge_z_score"),
                    edge_classification=sel_data["edge_classification"],
                    clv_odds_pct=sel_data.get("clv_odds_pct"),
                    clv_fair_prob_pct=sel_data.get("clv_fair_prob_pct"),
                    predicted_at_utc=now_utc,
                    odds_captured_at_utc=cap_dt,
                    pre_kickoff_verified=True,
                    immutable_record_sha256=rec_hash,
                    settlement_status="PENDING",
                    is_demo=bool(match.is_demo),
                )
                db.add(new_rec)
                db.flush()
                created_count += 1
                records_out.append(self._serialize_prospective_record(new_rec))

        db.commit()
        return {
            "match_id": match_id,
            "fixture_label": fixture_label,
            "kickoff_utc": kickoff_utc.isoformat(),
            "model_version": model_version,
            "created_records_count": created_count,
            "already_locked_records_count": existing_count,
            "records": records_out,
        }

    @staticmethod
    def _resolve_market_actual_selection(market_code: str, home_goals: int, away_goals: int) -> str:
        total_goals = int(home_goals) + int(away_goals)
        if market_code == "1X2":
            if home_goals > away_goals:
                return "HOME"
            if away_goals > home_goals:
                return "AWAY"
            return "DRAW"
        if market_code == "OVER_1_5":
            return "OVER" if total_goals >= 2 else "UNDER"
        if market_code in ("OVER_2_5", "UNDER_2_5"):
            return "OVER" if total_goals >= 3 else "UNDER"
        if market_code == "OVER_3_5":
            return "OVER" if total_goals >= 4 else "UNDER"
        if market_code == "BTTS":
            return "YES" if (home_goals >= 1 and away_goals >= 1) else "NO"
        raise ValueError(f"Mercado desconocido al liquidar resultado: {market_code}")

    def settle_finished_prospective_predictions(
        self,
        db: Session,
        match_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Incorpora el resultado final únicamente DESPUÉS de que el partido ha finalizado
        (`match.status == 'FINISHED'` y marcadores no nulos). Nunca altera los campos pre-partido.
        """
        self.ensure_phase4_tables_and_triggers(db)

        q = db.query(ProspectivePredictionRecord).filter(
            ProspectivePredictionRecord.settlement_status == "PENDING"
        )
        if match_id is not None:
            q = q.filter(ProspectivePredictionRecord.match_id == match_id)

        pending_rows = q.all()
        settled_count = 0
        skipped_not_finished = 0
        now_utc = datetime.now(timezone.utc)

        for r in pending_rows:
            match = db.query(Match).filter(Match.id == r.match_id).first()
            if (
                not match
                or match.status != "FINISHED"
                or match.home_goals is None
                or match.away_goals is None
            ):
                skipped_not_finished += 1
                continue

            kickoff_utc = _ensure_utc(match.kickoff_utc)
            if now_utc <= kickoff_utc:
                skipped_not_finished += 1
                continue

            winning_sel = self._resolve_market_actual_selection(
                r.market_code, int(match.home_goals), int(match.away_goals)
            )
            y_bin = 1 if r.selection_code == winning_sel else 0
            p_clip = float(np.clip(r.prob_model, 1e-6, 1.0 - 1e-6))
            brier_c = round((p_clip - float(y_bin)) ** 2, 6)
            ll_c = round(-float(y_bin * math.log(p_clip) + (1 - y_bin) * math.log(1.0 - p_clip)), 6)

            r.actual_outcome_code = winning_sel
            r.actual_outcome_binary = y_bin
            r.settlement_status = "WON" if y_bin == 1 else "LOST"
            r.brier_contribution = brier_c
            r.log_loss_contribution = ll_c
            r.settled_at_utc = now_utc
            settled_count += 1

        db.commit()
        return {
            "settled_records_count": settled_count,
            "skipped_unfinished_records_count": skipped_not_finished,
            "settled_at_utc": now_utc.isoformat(),
        }

    def list_prospective_ledger(
        self,
        db: Session,
        include_demo: bool = False,
        market_code: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """Devuelve el historial de predicciones prospectivas inmutables verificando la integridad
        del hash SHA-256 de cada registro.
        """
        self.ensure_phase4_tables_and_triggers(db)

        q = db.query(ProspectivePredictionRecord)
        if not include_demo:
            q = q.filter(ProspectivePredictionRecord.is_demo == False)
        if market_code is not None and isinstance(market_code, str):
            q = q.filter(ProspectivePredictionRecord.market_code == market_code.upper())

        limit_val = int(limit) if isinstance(limit, (int, float, str)) and str(limit).isdigit() else 100
        rows = q.order_by(ProspectivePredictionRecord.predicted_at_utc.desc()).limit(limit_val).all()
        items = []
        hash_verified_count = 0

        for r in rows:
            item = self._serialize_prospective_record(r)
            if item["sha256_integrity_verified"]:
                hash_verified_count += 1
            items.append(item)

        return {
            "total_returned": len(items),
            "sha256_integrity_verified_count": hash_verified_count,
            "all_hashes_valid": hash_verified_count == len(items),
            "include_demo": include_demo,
            "items": items,
        }

    def _serialize_prospective_record(self, r: ProspectivePredictionRecord) -> Dict[str, Any]:
        kickoff_iso = _ensure_utc(r.kickoff_utc).isoformat()
        pred_iso = _ensure_utc(r.predicted_at_utc).isoformat()
        recomputed_hash = compute_prospective_record_sha256(
            match_id=r.match_id,
            kickoff_utc_iso=kickoff_iso,
            model_version=r.model_version,
            model_code=r.model_code,
            market_code=r.market_code,
            selection_code=r.selection_code,
            prob_model=float(r.prob_model),
            observed_odds=r.observed_odds,
            predicted_at_utc_iso=pred_iso,
        )
        return {
            "id": r.id,
            "match_id": r.match_id,
            "competition_name": r.competition_name,
            "fixture_label": r.fixture_label,
            "kickoff_utc": kickoff_iso,
            "model_version": r.model_version,
            "model_code": r.model_code,
            "market_code": r.market_code,
            "selection_code": r.selection_code,
            "prob_model": r.prob_model,
            "fair_model_odds": r.fair_model_odds,
            "bookmaker_name": r.bookmaker_name,
            "opening_odds": r.opening_odds,
            "observed_odds": r.observed_odds,
            "closing_odds": r.closing_odds,
            "implied_prob_raw": r.implied_prob_raw,
            "bookmaker_overround": r.bookmaker_overround,
            "implied_prob_fair": r.implied_prob_fair,
            "implied_prob_fair_power": r.implied_prob_fair_power,
            "prob_edge": r.prob_edge,
            "expected_value": r.expected_value,
            "edge_z_score": r.edge_z_score,
            "edge_classification": r.edge_classification,
            "clv_odds_pct": r.clv_odds_pct,
            "clv_fair_prob_pct": r.clv_fair_prob_pct,
            "predicted_at_utc": pred_iso,
            "odds_captured_at_utc": _ensure_utc(r.odds_captured_at_utc).isoformat() if r.odds_captured_at_utc else None,
            "pre_kickoff_verified": bool(r.pre_kickoff_verified and _ensure_utc(r.predicted_at_utc) < _ensure_utc(r.kickoff_utc)),
            "immutable_record_sha256": r.immutable_record_sha256,
            "sha256_integrity_verified": recomputed_hash == r.immutable_record_sha256,
            "settlement_status": r.settlement_status,
            "actual_outcome_code": r.actual_outcome_code,
            "actual_outcome_binary": r.actual_outcome_binary,
            "brier_contribution": r.brier_contribution,
            "log_loss_contribution": r.log_loss_contribution,
            "settled_at_utc": _ensure_utc(r.settled_at_utc).isoformat() if r.settled_at_utc else None,
            "is_demo": bool(r.is_demo),
        }

    def evaluate_all_markets_historical_and_prospective(
        self,
        db: Session,
    ) -> Dict[str, Any]:
        """Evalúa por mercado (1X2, OVER_1_5, OVER_2_5, UNDER_2_5, OVER_3_5, BTTS):
        - Brier Score, Log Loss, Calibración (ECE), EV estimado, CLV, tamaño de muestra e intervalos
          de confianza al 95%.
        - Separa estrictamente los resultados HISTÓRICOS (N = 868 partidos reales de prueba retenida en v3.1.0)
          de los resultados PROSPECTIVOS REALES (`is_demo = False`) y de los registros DEMO (`is_demo = True`).
        """
        self.ensure_phase4_tables_and_triggers(db)

        v3_1_report_path = DATA_DIR / "real_historical" / "phase3_v3_1_validation_report.json"
        v3_1_data: Dict[str, Any] = {}
        if v3_1_report_path.exists():
            v3_1_data = json.loads(v3_1_report_path.read_text(encoding="utf-8"))

        # 1. Evaluación Histórica Retenida (N = 868 partidos reales OPENFOOTBALL_CC0, 2023-12-10 a 2024-06-02)
        historical_by_market: Dict[str, Any] = {}

        # Mapear métricas de 1X2 desde backtest_runs en la base de datos
        bt_1x2_ens = (
            db.query(BacktestRun)
            .join(MLModel, BacktestRun.model_id == MLModel.id)
            .filter(MLModel.version == "v3.1.0", MLModel.model_code == "ENSEMBLE")
            .order_by(BacktestRun.id.desc())
            .first()
        )
        if bt_1x2_ens:
            historical_by_market["1X2"] = {
                "market_code": "1X2",
                "primary_model_code": "ENSEMBLE",
                "co_optimal_model_code": "RANDOM_FOREST",
                "model_version": "v3.1.0",
                "sample_size_matches": bt_1x2_ens.total_predictions,
                "matches_with_real_market_odds": 0,
                "brier_score": bt_1x2_ens.brier_score,
                "baseline_brier_score": bt_1x2_ens.baseline_brier_score,
                "brier_improvement_vs_baseline": round(
                    bt_1x2_ens.brier_score - bt_1x2_ens.baseline_brier_score, 5
                ),
                "brier_ci_95": [-0.10494, -0.05658],
                "log_loss": bt_1x2_ens.log_loss,
                "ece_calibration": bt_1x2_ens.ece_calibration,
                "accuracy": bt_1x2_ens.accuracy,
                "expected_value_mean": None,
                "clv_mean_pct": None,
                "market_brier_score": None,
                "odds_availability_note": (
                    "0/868 partidos con cuotas reales en OPENFOOTBALL_CC0. No se inventan cuotas históricas."
                ),
            }

        goal_mkts_v3_1 = v3_1_data.get("section_2_v3_0_vs_v3_1_goal_markets_comparison", {})
        sec3_data = v3_1_data.get("section_3_statistical_tests_with_holm_correction", {})
        bt_vs_base = sec3_data.get("family_goal_markets_vs_baseline_m20", {})

        for mkt_code in ("OVER_1_5", "OVER_2_5", "UNDER_2_5", "OVER_3_5", "BTTS"):
            if mkt_code in goal_mkts_v3_1:
                m_obj = goal_mkts_v3_1[mkt_code]
                prim_code = m_obj.get("primary_model_selected_v3_1", "POISSON")
                p_metrics = m_obj["metrics_test_868"]["POISSON"]
                bt_info = (
                    bt_vs_base.get(f"{mkt_code}_POISSON_vs_BASE")
                    or bt_vs_base.get(f"{mkt_code}_POISSON_vs_BASELINE")
                    or {}
                )
                sample_n = p_metrics.get("n_matches", p_metrics.get("total_predictions", 868))
                historical_by_market[mkt_code] = {
                    "market_code": mkt_code,
                    "primary_model_code": prim_code,
                    "model_version": "v3.1.0",
                    "sample_size_matches": sample_n,
                    "matches_with_real_market_odds": 0,
                    "brier_score": p_metrics["brier_score"],
                    "baseline_brier_score": p_metrics["baseline_brier_score"],
                    "brier_improvement_vs_baseline": round(
                        p_metrics["brier_score"] - p_metrics["baseline_brier_score"], 5
                    ),
                    "brier_diff_vs_baseline_ci_95": bt_info.get("ci_95_diff"),
                    "log_loss": p_metrics["log_loss"],
                    "ece_calibration": p_metrics.get("ece_calibration", p_metrics.get("ece_5_bins", 0.0)),
                    "accuracy": p_metrics["accuracy"],
                    "expected_value_mean": None,
                    "clv_mean_pct": None,
                    "market_brier_score": None,
                    "odds_availability_note": (
                        "0/868 partidos con cuotas reales en OPENFOOTBALL_CC0. No se inventan cuotas históricas."
                    ),
                }

        # 2. Evaluación Prospectiva Real (`is_demo = False`) vs Sandbox Demostrativo (`is_demo = True`)
        prospective_real_by_market = self._aggregate_prospective_metrics_by_market(db, is_demo=False)
        prospective_demo_by_market = self._aggregate_prospective_metrics_by_market(db, is_demo=True)

        sample_size_requirements = {
            "even_money_odds_2_00_edge_3pct": required_prospective_sample_size_for_edge(2.00, 0.03),
            "typical_1x2_odds_2_50_edge_3pct": required_prospective_sample_size_for_edge(2.50, 0.03),
            "tight_edge_1_5pct_odds_2_00": required_prospective_sample_size_for_edge(2.00, 0.015),
        }

        return {
            "phase": "FASE_4_EVALUATION_REPORT",
            "component_version": PHASE4_COMPONENT_VERSION,
            "base_ml_version": BASE_ML_MODEL_VERSION,
            "strict_separation_policy": (
                "Los resultados históricos (868 partidos reales de prueba retenida en OPENFOOTBALL_CC0) "
                "se presentan estrictamente separados del registro prospectivo real (predicciones selladas "
                "antes del kickoff) y del entorno demostrativo (DEMO)."
            ),
            "roi_governance_warning": (
                "No se presenta ni afirma rentabilidad (ROI) demostrada: cualquier diferencia entre "
                "probabilidades del modelo y cuotas del mercado requiere una muestra prospectiva real "
                "verificable (N >= 752 a 1,734 apuestas con ventaja del 3% para cuota 2.00) antes de "
                "extraer conclusiones comerciales."
            ),
            "historical_test_evaluation_868_real_matches": historical_by_market,
            "prospective_real_evaluation": prospective_real_by_market,
            "prospective_demo_sandbox_evaluation": prospective_demo_by_market,
            "prospective_sample_size_requirements": sample_size_requirements,
        }

    def _aggregate_prospective_metrics_by_market(
        self,
        db: Session,
        is_demo: bool,
    ) -> Dict[str, Any]:
        rows = (
            db.query(ProspectivePredictionRecord)
            .filter(ProspectivePredictionRecord.is_demo == is_demo)
            .all()
        )
        out: Dict[str, Any] = {}
        for mkt_code in SUPPORTED_PHASE4_MARKETS.keys():
            m_rows = [r for r in rows if r.market_code == mkt_code]
            settled = [
                r
                for r in m_rows
                if r.settlement_status in ("WON", "LOST") and r.actual_outcome_binary is not None
            ]
            with_odds = [r for r in m_rows if r.observed_odds is not None]
            with_clv = [r for r in m_rows if r.clv_odds_pct is not None]
            candidates = [
                r for r in m_rows if r.edge_classification == "CANDIDATE_STATISTICAL_EDGE"
            ]

            brier_mean = None
            brier_ci95 = None
            ll_mean = None
            ece_val = None
            ev_mean = None
            clv_odds_mean = None
            clv_fair_mean = None
            clv_ci95 = None

            if settled:
                b_arr = np.array([float(r.brier_contribution) for r in settled], dtype=np.float64)
                l_arr = np.array([float(r.log_loss_contribution) for r in settled], dtype=np.float64)
                p_arr = np.array([float(r.prob_model) for r in settled], dtype=np.float64)
                y_arr = np.array([float(r.actual_outcome_binary) for r in settled], dtype=np.float64)
                brier_mean = round(float(np.mean(b_arr)), 5)
                ll_mean = round(float(np.mean(l_arr)), 5)
                ece_val = round(float(np.abs(np.mean(p_arr) - np.mean(y_arr))), 5)
                if len(b_arr) >= 2:
                    se = float(np.std(b_arr, ddof=1) / math.sqrt(len(b_arr)))
                    brier_ci95 = [round(brier_mean - 1.96 * se, 5), round(brier_mean + 1.96 * se, 5)]

            if with_odds:
                ev_vals = [float(r.expected_value) for r in with_odds if r.expected_value is not None]
                if ev_vals:
                    ev_mean = round(float(np.mean(ev_vals)), 5)

            if with_clv:
                c_odds = np.array([float(r.clv_odds_pct) for r in with_clv], dtype=np.float64)
                clv_odds_mean = round(float(np.mean(c_odds)), 5)
                c_fair = [float(r.clv_fair_prob_pct) for r in with_clv if r.clv_fair_prob_pct is not None]
                if c_fair:
                    clv_fair_mean = round(float(np.mean(c_fair)), 5)
                if len(c_odds) >= 2:
                    se_c = float(np.std(c_odds, ddof=1) / math.sqrt(len(c_odds)))
                    clv_ci95 = [round(clv_odds_mean - 1.96 * se_c, 5), round(clv_odds_mean + 1.96 * se_c, 5)]

            out[mkt_code] = {
                "market_code": mkt_code,
                "is_demo": is_demo,
                "total_registered_selections": len(m_rows),
                "pending_selections": len(m_rows) - len(settled),
                "settled_selections": len(settled),
                "selections_with_observed_odds": len(with_odds),
                "selections_with_closing_odds": len(with_clv),
                "candidate_statistical_edge_count": len(candidates),
                "brier_score": brier_mean,
                "brier_ci_95": brier_ci95,
                "log_loss": ll_mean,
                "calibration_gap_ece": ece_val,
                "expected_value_mean": ev_mean,
                "clv_odds_mean_pct": clv_odds_mean,
                "clv_fair_prob_mean_pct": clv_fair_mean,
                "clv_odds_ci_95": clv_ci95,
                "sample_sufficiency_status": (
                    "MUESTRA_INSUFICIENTE_PARA_DEMOSTRAR_VENTAJA"
                    if len(settled) < 500
                    else "MUESTRA_EN_EVALUACION"
                ),
            }
        return out


phase4_market_service = Phase4MarketAndProspectiveService()
