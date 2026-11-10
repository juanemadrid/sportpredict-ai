-- =============================================================================
-- SPORTPREDICT AI - ESQUEMA DE BASE DE DATOS POSTGRESQL / SUPABASE
-- Proyecto independiente. Prohibido ejecutar sobre bases de otros proyectos.
-- Incluye trazabilidad de fuentes, control de fuga temporal (Point-in-Time),
-- inmutabilidad de pronósticos pre-partido y arquitectura SaaS.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -----------------------------------------------------------------------------
-- 1. FUENTES DE DATOS Y CONTROL DE CUOTAS (SECCIÓN 7)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS data_sources (
    id SERIAL PRIMARY KEY,
    provider_code VARCHAR(50) UNIQUE NOT NULL, -- 'API_FOOTBALL', 'STATSBOMB_OPEN', 'AUTHORIZED_CSV', 'DEMO_SEED'
    display_name VARCHAR(120) NOT NULL,
    license_type VARCHAR(120) NOT NULL,
    daily_quota_limit INTEGER NOT NULL DEFAULT 100,
    requests_used_today INTEGER NOT NULL DEFAULT 0,
    quota_reset_date DATE NOT NULL DEFAULT CURRENT_DATE,
    status VARCHAR(30) NOT NULL DEFAULT 'NOT_CONFIGURED', -- 'ACTIVE', 'NOT_CONFIGURED', 'QUOTA_EXHAUSTED', 'ERROR'
    last_sync_at TIMESTAMPTZ,
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sync_logs (
    id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
    endpoint_or_file VARCHAR(255) NOT NULL,
    records_processed INTEGER NOT NULL DEFAULT 0,
    records_inserted INTEGER NOT NULL DEFAULT 0,
    duplicates_detected INTEGER NOT NULL DEFAULT 0,
    missing_values_detected INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(30) NOT NULL, -- 'SUCCESS', 'CACHE_HIT', 'BLOCKED_QUOTA', 'ERROR'
    notes TEXT,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 2. COMPETICIONES, TEMPORADAS Y EQUIPOS NORMALIZADOS
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS competitions (
    id SERIAL PRIMARY KEY,
    code VARCHAR(40) UNIQUE NOT NULL,
    name VARCHAR(120) NOT NULL,
    country VARCHAR(80) NOT NULL,
    tier INTEGER NOT NULL DEFAULT 1,
    has_xg_coverage BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    source_name VARCHAR(80) NOT NULL,
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS teams (
    id SERIAL PRIMARY KEY,
    canonical_name VARCHAR(120) UNIQUE NOT NULL,
    short_code VARCHAR(15) NOT NULL,
    country VARCHAR(80) NOT NULL,
    crest_url VARCHAR(500),
    current_elo NUMERIC(8, 2) NOT NULL DEFAULT 1500.00,
    matches_indexed INTEGER NOT NULL DEFAULT 0,
    source_name VARCHAR(80) NOT NULL,
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS team_aliases (
    id SERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    provider_code VARCHAR(50) NOT NULL,
    external_id VARCHAR(80),
    alias_name VARCHAR(120) NOT NULL,
    UNIQUE(provider_code, alias_name)
);

-- -----------------------------------------------------------------------------
-- 3. PARTIDOS Y VARIABLES DE ANÁLISIS DEPORTIVO (SECCIÓN 4)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS matches (
    id SERIAL PRIMARY KEY,
    external_ref VARCHAR(100) UNIQUE NOT NULL,
    competition_id INTEGER NOT NULL REFERENCES competitions(id),
    season VARCHAR(20) NOT NULL,
    matchday INTEGER,
    kickoff_utc TIMESTAMPTZ NOT NULL,
    status VARCHAR(25) NOT NULL DEFAULT 'SCHEDULED', -- 'SCHEDULED', 'FINISHED', 'POSTPONED'
    home_team_id INTEGER NOT NULL REFERENCES teams(id),
    away_team_id INTEGER NOT NULL REFERENCES teams(id),
    -- Resultados finales y al descanso (NULL mientras status = 'SCHEDULED')
    home_goals INTEGER,
    away_goals INTEGER,
    ht_home_goals INTEGER,
    ht_away_goals INTEGER,
    outcome_1x2 VARCHAR(5), -- 'H', 'D', 'A' (solo cuando FINISHED)
    -- Contexto pre-partido verificado con fecha de captura < kickoff_utc
    home_league_pos INTEGER,
    away_league_pos INTEGER,
    home_rest_days INTEGER,
    away_rest_days INTEGER,
    lineups_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    match_context VARCHAR(120) DEFAULT 'REGULAR_SEASON',
    -- Trazabilidad obligatoria
    source_name VARCHAR(80) NOT NULL,
    source_license VARCHAR(120) NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT chk_different_teams CHECK (home_team_id <> away_team_id)
);

CREATE INDEX IF NOT EXISTS idx_matches_kickoff ON matches(kickoff_utc);
CREATE INDEX IF NOT EXISTS idx_matches_teams ON matches(home_team_id, away_team_id);

-- Estadísticas detalladas de cada equipo en un partido (histórico post-partido)
CREATE TABLE IF NOT EXISTS match_team_stats (
    id SERIAL PRIMARY KEY,
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    team_id INTEGER NOT NULL REFERENCES teams(id),
    is_home BOOLEAN NOT NULL,
    xg NUMERIC(5, 2), -- NULL si la fuente no proporciona xG real
    shots INTEGER,
    shots_on_target INTEGER,
    corners INTEGER,
    yellow_cards INTEGER,
    red_cards INTEGER,
    fouls INTEGER,
    possession_pct NUMERIC(5, 2),
    source_name VARCHAR(80) NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE(match_id, team_id)
);

-- Lesiones, sanciones y disponibilidad de jugadores (estrictamente pre-partido)
CREATE TABLE IF NOT EXISTS player_availabilities (
    id SERIAL PRIMARY KEY,
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    team_id INTEGER NOT NULL REFERENCES teams(id),
    player_name VARCHAR(120) NOT NULL,
    status_type VARCHAR(30) NOT NULL, -- 'INJURED', 'SUSPENDED', 'DOUBTFUL', 'CONFIRMED_XI'
    position VARCHAR(30),
    impact_note VARCHAR(255),
    source_name VARCHAR(80) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    is_demo BOOLEAN NOT NULL DEFAULT FALSE
);

-- Vector de variables predictivas Point-in-Time (calculado estrictamente < kickoff_utc)
CREATE TABLE IF NOT EXISTS pre_match_features (
    id SERIAL PRIMARY KEY,
    match_id INTEGER UNIQUE NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    computed_before_kickoff_at TIMESTAMPTZ NOT NULL,
    -- Elo pre-partido
    home_elo_pre NUMERIC(8, 2) NOT NULL,
    away_elo_pre NUMERIC(8, 2) NOT NULL,
    elo_diff NUMERIC(8, 2) NOT NULL,
    -- Últimos 5 partidos
    home_pts_last5 NUMERIC(5, 2),
    away_pts_last5 NUMERIC(5, 2),
    home_gf_last5 NUMERIC(5, 2),
    home_ga_last5 NUMERIC(5, 2),
    away_gf_last5 NUMERIC(5, 2),
    away_ga_last5 NUMERIC(5, 2),
    -- Últimos 10 partidos
    home_pts_last10 NUMERIC(5, 2),
    away_pts_last10 NUMERIC(5, 2),
    home_gf_last10 NUMERIC(5, 2),
    home_ga_last10 NUMERIC(5, 2),
    away_gf_last10 NUMERIC(5, 2),
    away_ga_last10 NUMERIC(5, 2),
    -- Rendimiento específico Local / Visitante
    home_home_gf_avg NUMERIC(5, 2),
    home_home_ga_avg NUMERIC(5, 2),
    away_away_gf_avg NUMERIC(5, 2),
    away_away_ga_avg NUMERIC(5, 2),
    -- xG, Tiros, Córners y Tarjetas promedios previos
    home_xg_last5 NUMERIC(5, 2),
    away_xg_last5 NUMERIC(5, 2),
    home_sot_last5 NUMERIC(5, 2),
    away_sot_last5 NUMERIC(5, 2),
    home_corners_last5 NUMERIC(5, 2),
    away_corners_last5 NUMERIC(5, 2),
    home_cards_last5 NUMERIC(5, 2),
    away_cards_last5 NUMERIC(5, 2),
    -- Enfrentamientos directos previos (H2H)
    h2h_matches_count INTEGER NOT NULL DEFAULT 0,
    h2h_home_win_rate NUMERIC(5, 4),
    -- Bajas reportadas pre-partido
    home_missing_players INTEGER NOT NULL DEFAULT 0,
    away_missing_players INTEGER NOT NULL DEFAULT 0,
    source_name VARCHAR(80) NOT NULL,
    is_demo BOOLEAN NOT NULL DEFAULT FALSE
);

-- -----------------------------------------------------------------------------
-- 4. CATÁLOGO DE MERCADOS PROGRESIVOS Y CUOTAS (SECCIONES 5 Y 6)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_catalog (
    market_code VARCHAR(40) PRIMARY KEY,
    display_name VARCHAR(100) NOT NULL,
    tier_level INTEGER NOT NULL CHECK (tier_level IN (1, 2, 3)),
    min_samples_required INTEGER NOT NULL DEFAULT 100,
    is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    status_reason VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS odds_snapshots (
    id SERIAL PRIMARY KEY,
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    bookmaker_name VARCHAR(80) NOT NULL,
    market_code VARCHAR(40) NOT NULL REFERENCES market_catalog(market_code),
    selection_code VARCHAR(30) NOT NULL, -- 'HOME', 'DRAW', 'AWAY', 'OVER_2_5', 'UNDER_2_5', 'BTTS_YES', etc.
    decimal_odds NUMERIC(8, 3) NOT NULL CHECK (decimal_odds > 1.0),
    implied_prob_raw NUMERIC(6, 5) NOT NULL,
    overround_margin NUMERIC(6, 5) NOT NULL,
    implied_prob_fair NUMERIC(6, 5) NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL,
    source_name VARCHAR(80) NOT NULL,
    is_demo BOOLEAN NOT NULL DEFAULT FALSE
);

-- -----------------------------------------------------------------------------
-- 5. REGISTRO DE MODELOS ML, PREDICCIONES INMUTABLES Y BACKTESTING (SECCIONES 3, 8, 9, 10)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ml_models (
    id SERIAL PRIMARY KEY,
    model_code VARCHAR(50) NOT NULL, -- 'POISSON', 'ELO', 'RANDOM_FOREST', 'XGBOOST', 'ENSEMBLE', 'BASELINE'
    version VARCHAR(30) NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    calibration_method VARCHAR(30) NOT NULL DEFAULT 'NONE', -- 'NONE', 'SIGMOID', 'ISOTONIC'
    artifact_path VARCHAR(255),
    train_matches_count INTEGER NOT NULL DEFAULT 0,
    val_brier_score NUMERIC(7, 5),
    val_log_loss NUMERIC(7, 5),
    test_brier_score NUMERIC(7, 5),
    test_log_loss NUMERIC(7, 5),
    ensemble_weight NUMERIC(5, 4) DEFAULT 0.0,
    hyperparameters_json TEXT,
    feature_importance_json TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    trained_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(model_code, version)
);

CREATE TABLE IF NOT EXISTS predictions (
    id SERIAL PRIMARY KEY,
    match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    model_id INTEGER NOT NULL REFERENCES ml_models(id),
    market_code VARCHAR(40) NOT NULL REFERENCES market_catalog(market_code),
    selection_code VARCHAR(30) NOT NULL,
    -- Métricas de probabilidad y valor (Sección 6)
    prob_estimated NUMERIC(6, 5) NOT NULL CHECK (prob_estimated >= 0 AND prob_estimated <= 1),
    fair_decimal_odds NUMERIC(10, 3) NOT NULL,
    available_decimal_odds NUMERIC(10, 3),
    bookmaker_margin NUMERIC(6, 5),
    market_implied_prob_fair NUMERIC(6, 5),
    prob_edge_diff NUMERIC(7, 5),
    expected_value NUMERIC(7, 5),
    uncertainty_score NUMERIC(6, 5) NOT NULL,
    uncertainty_label VARCHAR(20) NOT NULL, -- 'BAJA', 'MEDIA', 'ALTA'
    explanation_factors_json TEXT,
    -- Auditoría temporal y liquidación inmutable (Sección 10)
    predicted_before_kickoff_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    odds_captured_at TIMESTAMPTZ,
    settlement_status VARCHAR(20) NOT NULL DEFAULT 'PENDING', -- 'PENDING', 'WON', 'LOST', 'VOID'
    actual_result_code VARCHAR(30),
    brier_contribution NUMERIC(7, 5),
    is_demo BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_predictions_match_model ON predictions(match_id, model_id);

-- Registro reproducible de ejecuciones de validación científica y backtesting
CREATE TABLE IF NOT EXISTS backtest_runs (
    id SERIAL PRIMARY KEY,
    run_uid VARCHAR(64) UNIQUE NOT NULL,
    model_id INTEGER NOT NULL REFERENCES ml_models(id),
    market_code VARCHAR(40) NOT NULL,
    train_period VARCHAR(80) NOT NULL,
    val_period VARCHAR(80) NOT NULL,
    test_period VARCHAR(80) NOT NULL,
    total_predictions INTEGER NOT NULL,
    accuracy NUMERIC(6, 5) NOT NULL,
    precision_macro NUMERIC(6, 5) NOT NULL,
    recall_macro NUMERIC(6, 5) NOT NULL,
    f1_macro NUMERIC(6, 5) NOT NULL,
    brier_score NUMERIC(7, 5) NOT NULL,
    log_loss NUMERIC(7, 5) NOT NULL,
    ece_calibration NUMERIC(7, 5) NOT NULL,
    baseline_brier_score NUMERIC(7, 5) NOT NULL,
    market_brier_score NUMERIC(7, 5),
    simulated_bets_count INTEGER NOT NULL DEFAULT 0,
    simulated_roi_pct NUMERIC(8, 3) NOT NULL DEFAULT 0.0,
    simulated_yield_pct NUMERIC(8, 3) NOT NULL DEFAULT 0.0,
    calibration_curve_json TEXT NOT NULL,
    by_competition_json TEXT NOT NULL,
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 6. SISTEMA DE USUARIOS, ROLES Y PLANES SAAS (SECCIÓN 12)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subscription_plans (
    plan_code VARCHAR(30) PRIMARY KEY, -- 'FREE', 'PREMIUM', 'PRO'
    display_name VARCHAR(80) NOT NULL,
    daily_analysis_limit INTEGER NOT NULL,
    allowed_market_tiers INTEGER NOT NULL,
    includes_odds_comparator BOOLEAN NOT NULL DEFAULT FALSE,
    includes_full_history BOOLEAN NOT NULL DEFAULT FALSE,
    includes_model_benchmarks BOOLEAN NOT NULL DEFAULT FALSE,
    billing_active BOOLEAN NOT NULL DEFAULT FALSE -- Desactivado según requerimiento
);

CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(120) NOT NULL,
    role VARCHAR(25) NOT NULL DEFAULT 'USER', -- 'USER', 'ANALYST', 'ADMIN'
    plan_code VARCHAR(30) NOT NULL REFERENCES subscription_plans(plan_code) DEFAULT 'FREE',
    age_verified_18plus BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
