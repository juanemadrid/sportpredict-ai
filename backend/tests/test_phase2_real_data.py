from datetime import datetime, timedelta, timezone
import numpy as np
import pytest

from app.ingestion.real_open_data_fetcher import OpenFootballRealDataAdapter
from app.ml.features import HistoricalMatchRecord, PointInTimeFeatureBuilder
from app.ml.models.elo_model import DynamicEloModel
from app.ml.models.ensemble_model import TemporalWeightedEnsembleModel


def test_real_team_and_datetime_normalization():
    norm_name, changed = OpenFootballRealDataAdapter.normalize_team_name("FC Internazionale Milano")
    assert norm_name == "Inter de Milán"
    assert changed is True

    dt, had_time = OpenFootballRealDataAdapter.normalize_kickoff_utc("2023-08-11", "19:45")
    assert dt is not None
    assert had_time is True
    assert dt.tzinfo == timezone.utc

    dt_default, had_time2 = OpenFootballRealDataAdapter.normalize_kickoff_utc("2023-08-12", None)
    assert dt_default is not None
    assert had_time2 is False
    assert dt_default.hour == 15


def test_batch_chronological_features_exact_equivalence_and_no_leakage():
    """Verifica que el cálculo incremental O(N) agrupado por kickoff_utc produzca exactamente
    las mismas variables que el cálculo individual estricto sin fuga temporal.
    """
    base_dt = datetime(2023, 9, 1, 15, 0, tzinfo=timezone.utc)
    records = [
        HistoricalMatchRecord(
            match_id=101,
            competition_id=1,
            season="2023-24",
            kickoff_utc=base_dt,
            home_team_id=1,
            away_team_id=2,
            home_goals=2,
            away_goals=1,
            status="FINISHED",
            is_demo=False,
        ),
        HistoricalMatchRecord(
            match_id=102,
            competition_id=1,
            season="2023-24",
            kickoff_utc=base_dt + timedelta(days=7),
            home_team_id=2,
            away_team_id=1,
            home_goals=0,
            away_goals=3,
            status="FINISHED",
            is_demo=False,
        ),
        HistoricalMatchRecord(
            match_id=103,
            competition_id=1,
            season="2023-24",
            kickoff_utc=base_dt + timedelta(days=14),
            home_team_id=1,
            away_team_id=2,
            home_goals=1,
            away_goals=1,
            status="FINISHED",
            is_demo=False,
        ),
    ]

    elo_batch = DynamicEloModel()
    feats_batch, _ = PointInTimeFeatureBuilder.build_all_chronological_features_and_elo(records, elo_batch)

    elo_single = DynamicEloModel()
    for idx, r in enumerate(records):
        h_e = elo_single.get_rating(r.home_team_id)
        a_e = elo_single.get_rating(r.away_team_id)
        feat_s = PointInTimeFeatureBuilder.build_features_for_match(r, records[:idx], h_e, a_e)
        assert feats_batch[r.match_id]["home_gf_last5"] == feat_s["home_gf_last5"]
        assert feats_batch[r.match_id]["elo_diff"] == feat_s["elo_diff"]
        elo_single.update_after_match(
            r.home_team_id, r.away_team_id, int(r.home_goals), int(r.away_goals), r.kickoff_utc, r.match_id
        )


def test_simplex_ensemble_prunes_non_contributing_models():
    """Verifica que el optimizador SLSQP del Ensamble no fuerce pesos positivos para modelos deficientes."""
    ens = TemporalWeightedEnsembleModel(prune_threshold=0.01)
    y_val = [0, 1, 2, 0, 2, 0]

    # Modelo bueno (cercano a la realidad) vs Modelo ruidoso/deficiente
    good_mat = np.array(
        [
            [0.70, 0.20, 0.10],
            [0.20, 0.60, 0.20],
            [0.15, 0.20, 0.65],
            [0.65, 0.20, 0.15],
            [0.10, 0.25, 0.65],
            [0.75, 0.15, 0.10],
        ]
    )
    bad_mat = np.array(
        [
            [0.15, 0.25, 0.60],
            [0.60, 0.10, 0.30],
            [0.60, 0.25, 0.15],
            [0.20, 0.30, 0.50],
            [0.55, 0.30, 0.15],
            [0.20, 0.20, 0.60],
        ]
    )

    weights = ens.optimize_simplex_weights(
        val_prob_matrices={"POISSON": good_mat, "BAD_MODEL": bad_mat},
        y_val_indices=y_val,
        val_brier_by_model={"POISSON": 0.22, "BAD_MODEL": 0.85},
        baseline_brier=0.66,
    )
    assert weights["POISSON"] == pytest.approx(1.0, abs=1e-4)
    assert weights["BAD_MODEL"] == 0.0
    assert "BAD_MODEL" in ens.excluded_models
