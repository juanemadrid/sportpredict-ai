from datetime import date, datetime, timezone
from typing import Optional
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    license_type: Mapped[str] = mapped_column(String(120), nullable=False)
    daily_quota_limit: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    requests_used_today: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quota_reset_date: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="NOT_CONFIGURED", nullable=False)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), nullable=False)
    endpoint_or_file: Mapped[str] = mapped_column(String(255), nullable=False)
    records_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    records_inserted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicates_detected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    missing_values_detected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Competition(Base):
    __tablename__ = "competitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    country: Mapped[str] = mapped_column(String(80), nullable=False)
    tier: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    has_xg_coverage: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source_name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    short_code: Mapped[str] = mapped_column(String(15), nullable=False)
    country: Mapped[str] = mapped_column(String(80), nullable=False)
    crest_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    current_elo: Mapped[float] = mapped_column(Float, default=1500.0, nullable=False)
    matches_indexed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class TeamAlias(Base):
    __tablename__ = "team_aliases"
    __table_args__ = (UniqueConstraint("provider_code", "alias_name", name="uq_provider_alias"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    alias_name: Mapped[str] = mapped_column(String(120), nullable=False)


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_ref: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), nullable=False)
    season: Mapped[str] = mapped_column(String(20), nullable=False)
    matchday: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    kickoff_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(25), default="SCHEDULED", nullable=False)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)

    home_goals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    away_goals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ht_home_goals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ht_away_goals: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    outcome_1x2: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # 'H', 'D', 'A'

    home_league_pos: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    away_league_pos: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    home_rest_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    away_rest_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    lineups_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    match_context: Mapped[str] = mapped_column(String(120), default="REGULAR_SEASON", nullable=False)

    source_name: Mapped[str] = mapped_column(String(80), nullable=False)
    source_license: Mapped[str] = mapped_column(String(120), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class MatchTeamStat(Base):
    __tablename__ = "match_team_stats"
    __table_args__ = (UniqueConstraint("match_id", "team_id", name="uq_match_team_stat"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    is_home: Mapped[bool] = mapped_column(Boolean, nullable=False)
    xg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    shots: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    shots_on_target: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    corners: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    yellow_cards: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    red_cards: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fouls: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    possession_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source_name: Mapped[str] = mapped_column(String(80), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class PlayerAvailability(Base):
    __tablename__ = "player_availabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False)
    player_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status_type: Mapped[str] = mapped_column(String(30), nullable=False)  # 'INJURED', 'SUSPENDED', 'DOUBTFUL', 'CONFIRMED_XI'
    position: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    impact_note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_name: Mapped[str] = mapped_column(String(80), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class MarketCatalog(Base):
    __tablename__ = "market_catalog"

    market_code: Mapped[str] = mapped_column(String(40), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tier_level: Mapped[int] = mapped_column(Integer, nullable=False)
    min_samples_required: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status_reason: Mapped[str] = mapped_column(String(255), nullable=False)


class OddsSnapshot(Base):
    __tablename__ = "odds_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    bookmaker_name: Mapped[str] = mapped_column(String(80), nullable=False)
    market_code: Mapped[str] = mapped_column(ForeignKey("market_catalog.market_code"), nullable=False)
    selection_code: Mapped[str] = mapped_column(String(30), nullable=False)
    decimal_odds: Mapped[float] = mapped_column(Float, nullable=False)
    implied_prob_raw: Mapped[float] = mapped_column(Float, nullable=False)
    overround_margin: Mapped[float] = mapped_column(Float, nullable=False)
    implied_prob_fair: Mapped[float] = mapped_column(Float, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    source_name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class MLModel(Base):
    __tablename__ = "ml_models"
    __table_args__ = (UniqueConstraint("model_code", "version", name="uq_model_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_code: Mapped[str] = mapped_column(String(50), nullable=False)  # 'POISSON', 'ELO', 'RANDOM_FOREST', 'XGBOOST', 'ENSEMBLE', 'BASELINE'
    version: Mapped[str] = mapped_column(String(30), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    calibration_method: Mapped[str] = mapped_column(String(30), default="NONE", nullable=False)
    artifact_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    train_matches_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    val_brier_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    val_log_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    test_brier_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    test_log_loss: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ensemble_weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    hyperparameters_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    feature_importance_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("ml_models.id"), nullable=False)
    market_code: Mapped[str] = mapped_column(ForeignKey("market_catalog.market_code"), nullable=False)
    selection_code: Mapped[str] = mapped_column(String(30), nullable=False)

    prob_estimated: Mapped[float] = mapped_column(Float, nullable=False)
    fair_decimal_odds: Mapped[float] = mapped_column(Float, nullable=False)
    available_decimal_odds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bookmaker_margin: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_implied_prob_fair: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    prob_edge_diff: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    uncertainty_score: Mapped[float] = mapped_column(Float, nullable=False)
    uncertainty_label: Mapped[str] = mapped_column(String(20), nullable=False)
    explanation_factors_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    predicted_before_kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    odds_captured_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    settlement_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    actual_result_code: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    brier_contribution: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_uid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    model_id: Mapped[int] = mapped_column(ForeignKey("ml_models.id"), nullable=False)
    market_code: Mapped[str] = mapped_column(String(40), nullable=False)
    train_period: Mapped[str] = mapped_column(String(80), nullable=False)
    val_period: Mapped[str] = mapped_column(String(80), nullable=False)
    test_period: Mapped[str] = mapped_column(String(80), nullable=False)
    total_predictions: Mapped[int] = mapped_column(Integer, nullable=False)
    accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    precision_macro: Mapped[float] = mapped_column(Float, nullable=False)
    recall_macro: Mapped[float] = mapped_column(Float, nullable=False)
    f1_macro: Mapped[float] = mapped_column(Float, nullable=False)
    brier_score: Mapped[float] = mapped_column(Float, nullable=False)
    log_loss: Mapped[float] = mapped_column(Float, nullable=False)
    ece_calibration: Mapped[float] = mapped_column(Float, nullable=False)
    baseline_brier_score: Mapped[float] = mapped_column(Float, nullable=False)
    market_brier_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    simulated_bets_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    simulated_roi_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    simulated_yield_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    calibration_curve_json: Mapped[str] = mapped_column(Text, nullable=False)
    by_competition_json: Mapped[str] = mapped_column(Text, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MarketOddsRecord(Base):
    """Captura estructurada de cuotas reales del mercado para Fase 4 (1X2, OVER_1_5, OVER_2_5,
    UNDER_2_5, OVER_3_5, BTTS) con trazabilidad completa de operador, licencia y etapa de línea
    (inicial / actual / cierre). Nunca inventa ni rellena cuotas faltantes.
    """

    __tablename__ = "market_odds_records"
    __table_args__ = (
        UniqueConstraint(
            "match_id",
            "bookmaker_name",
            "market_code",
            "selection_code",
            name="uq_phase4_match_bookmaker_market_sel",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    bookmaker_name: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_source: Mapped[str] = mapped_column(String(80), nullable=False)
    license_type: Mapped[str] = mapped_column(String(120), nullable=False)
    commercial_saas_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    market_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    selection_code: Mapped[str] = mapped_column(String(30), nullable=False)

    opening_odds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_odds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    closing_odds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    opening_captured_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    current_captured_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closing_captured_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    implied_prob_raw: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bookmaker_overround: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    implied_prob_fair_prop: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    implied_prob_fair_power: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ProspectivePredictionRecord(Base):
    """Registro prospectivo inmutable de predicciones pre-partido (Sección 4 de Fase 4).
    Toda predicción debe generarse antes de `kickoff_utc` (`predicted_at_utc < kickoff_utc`).
    Los atributos pre-partido quedan sellados con SHA-256 y protegidos mediante triggers SQLite
    contra cualquier modificación retroactiva o borrado. El resultado real se liquida únicamente
    después de finalizado el encuentro.
    """

    __tablename__ = "prospective_predictions"
    __table_args__ = (
        UniqueConstraint(
            "match_id",
            "model_version",
            "market_code",
            "selection_code",
            name="uq_prospective_match_ver_mkt_sel",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), nullable=False, index=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), nullable=False)
    competition_name: Mapped[str] = mapped_column(String(120), nullable=False)
    fixture_label: Mapped[str] = mapped_column(String(200), nullable=False)
    kickoff_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    model_version: Mapped[str] = mapped_column(String(40), nullable=False)
    model_code: Mapped[str] = mapped_column(String(50), nullable=False)
    market_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    selection_code: Mapped[str] = mapped_column(String(30), nullable=False)

    prob_model: Mapped[float] = mapped_column(Float, nullable=False)
    fair_model_odds: Mapped[float] = mapped_column(Float, nullable=False)

    bookmaker_name: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    opening_odds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    observed_odds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    closing_odds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    implied_prob_raw: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bookmaker_overround: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    implied_prob_fair: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    implied_prob_fair_power: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    prob_edge: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expected_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    edge_z_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    edge_classification: Mapped[str] = mapped_column(String(40), default="NO_ODDS_AVAILABLE", nullable=False)

    clv_odds_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    clv_fair_prob_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    predicted_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    odds_captured_at_utc: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    pre_kickoff_verified: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    immutable_record_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    settlement_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    actual_outcome_code: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    actual_outcome_binary: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    brier_contribution: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    log_loss_contribution: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    settled_at_utc: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)



# =============================================================================
# FASE 5 - USUARIOS SAAS (Supabase Auth) Y CONTROL DE CUOTAS POR PLAN
# =============================================================================
class UserProfile(Base):
    """Perfil local de un usuario autenticado por Supabase Auth.
    La identidad (`id` = claim `sub` del JWT) la emite Supabase; el rol y el plan SaaS
    los administra exclusivamente un ADMIN desde la API (nunca el propio usuario).
    """

    __tablename__ = "user_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(20), default="USER", nullable=False)
    plan_code: Mapped[str] = mapped_column(String(20), default="FREE", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class UsageCounter(Base):
    """Contador diario de análisis consumidos por usuario (límite por plan SaaS)."""

    __tablename__ = "usage_counters"
    __table_args__ = (UniqueConstraint("user_id", "usage_date", "metric", name="uq_usage_user_day_metric"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("user_profiles.id"), nullable=False, index=True)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    metric: Mapped[str] = mapped_column(String(40), default="match_analysis", nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
