export interface SelectionValuation {
  selection_code: string;
  prob_estimated: number;
  fair_decimal_odds: number;
  available_decimal_odds: number | null;
  bookmaker_margin: number | null;
  market_implied_prob_fair: number | null;
  prob_edge_diff: number | null;
  expected_value: number | null;
  uncertainty_score: number;
  uncertainty_label: "BAJA" | "MEDIA" | "ALTA";
}

export interface MatchSummaryItem {
  match: {
    id: number;
    external_ref: string;
    competition_code: string;
    competition_name: string;
    season: string;
    matchday: number | null;
    kickoff_utc: string;
    status: "SCHEDULED" | "FINISHED" | "POSTPONED";
    home_team: { id: number; name: string; short_code: string; elo_pre_match: number };
    away_team: { id: number; name: string; short_code: string; elo_pre_match: number };
    home_goals: number | null;
    away_goals: number | null;
    outcome_1x2: string | null;
    lineups_confirmed: boolean;
    source_name: string;
    source_license: string;
    captured_at: string;
    is_demo: boolean;
  };
  model_version: string;
  expected_goals: { home: number; away: number };
  market_1x2: Record<string, SelectionValuation>;
  market_ou_2_5: Record<string, SelectionValuation>;
  best_value_opportunity: {
    selection: string | null;
    expected_value: number | null;
  };
}

export interface DetailedMatchAnalysis {
  match: MatchSummaryItem["match"];
  model_version: string;
  bookmaker_source: string | null;
  odds_captured_at: string | null;
  pre_match_features: Record<string, number | string>;
  player_availabilities: Array<{
    team_id: number;
    team_name: string;
    player_name: string;
    status_type: string;
    position: string | null;
    impact_note: string | null;
    source_name: string;
    recorded_at: string;
  }>;
  poisson_goal_model: {
    expected_goals_home: number;
    expected_goals_away: number;
    home_goal_probabilities: Record<string, number>;
    away_goal_probabilities: Record<string, number>;
    top_exact_scores: Array<{
      score: string;
      home_goals: number;
      away_goals: number;
      probability: number;
    }>;
  };
  models_comparison_1x2: Record<string, Record<string, number>>;
  ensemble_weights: Record<string, number>;
  markets: Record<
    string,
    {
      market_code: string;
      display_name: string;
      tier_level: number;
      selections: Record<string, SelectionValuation>;
    }
  >;
  market_governance: Array<{
    market_code: string;
    display_name: string;
    tier_level: number;
    is_enabled: boolean;
    min_samples_required: number;
    status_reason: string;
  }>;
  explanation_factors: string[];
  user_plan_applied?: string;
}

export interface ModelComparisonEntry {
  id: number;
  model_code: string;
  display_name: string;
  version: string;
  calibration_method: string;
  artifact_path: string;
  train_matches_count: number;
  ensemble_weight: number;
  val_brier_score: number;
  val_log_loss: number;
  test_brier_score: number;
  test_log_loss: number;
  trained_at: string;
  feature_importance: Record<string, number>;
  backtest: {
    run_uid: string;
    train_period: string;
    val_period: string;
    test_period: string;
    total_predictions: number;
    accuracy: number;
    precision_macro: number;
    recall_macro: number;
    f1_macro: number;
    brier_score: number;
    log_loss: number;
    ece_calibration: number;
    baseline_brier_score: number;
    market_brier_score: number | null;
    simulated_bets_count: number;
    simulated_roi_pct: number;
    simulated_yield_pct: number;
    calibration_curve: Array<{
      bin_range: string;
      count: number;
      mean_predicted_prob: number;
      empirical_win_rate: number;
      calibration_gap: number;
    }>;
    by_competition: Record<string, { matches: number; accuracy: number; brier_score: number }>;
    is_demo: boolean;
  } | null;
}
