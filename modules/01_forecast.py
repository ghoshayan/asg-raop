"""
modules/01_forecast.py — Temporal Forecaster
=============================================
Module 1 of the ASG-RAOP pipeline.

Responsibilities:
  1. Ingest 15-minute German solar generation data from SMARD.de (Filter 1226)
     — or from a local fixture file for offline/reproducible development.
  2. Clean and enforce physical non-negativity: P_solar >= 0.0  (INV-001)
  3. Engineer time-series features for LightGBM.
  4. Train / load a LightGBM quantile regression model (q=0.10, 0.50, 0.90).
  5. Produce a ForecastOutput Pydantic model for downstream modules.

Public API:
    run(mode="fixture" | "live",
        fixture_path: Optional[Path],
        lookback_hours: int) -> ForecastOutput
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports — only pulled in when actually training/predicting
# ---------------------------------------------------------------------------
try:
    import lightgbm as lgb  # type: ignore

    _LGB_AVAILABLE = True
except ImportError:
    _LGB_AVAILABLE = False
    logger.warning("lightgbm not installed — will fall back to MA baseline.")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SMARD_INDEX_ENDPOINT = (
    "https://www.smard.de/app/chart_data/1226/DE/index_quarterhour.json"
)
SMARD_CHUNK_TEMPLATE = (
    "https://www.smard.de/app/chart_data/1226/DE/1226_DE_quarterhour_{ts}.json"
)
THERMAL_LIMIT_PCT = 80.0
FIXTURE_PATH_DEFAULT = Path(__file__).parent.parent / "tests" / "fixtures" / "smard_30d.json"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_fixture(fixture_path: Path) -> pd.DataFrame:
    """Load SMARD data from a local JSON fixture file."""
    logger.info("Loading SMARD fixture from %s", fixture_path)
    with open(fixture_path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return _parse_smard_json(raw)


def _fetch_live(lookback_hours: int = 72) -> pd.DataFrame:
    """
    Fetch live SMARD.de quarter-hour generation data via official index.
    """
    import requests  # deferred so fixture mode never requires network

    logger.info("Fetching live SMARD data (lookback=%d h)…", lookback_hours)
    resp = requests.get(SMARD_INDEX_ENDPOINT, timeout=30)
    resp.raise_for_status()
    index_data = resp.json()
    ts_list = index_data.get("timestamps", [])
    if not ts_list:
        raise ValueError("SMARD index returned no timestamps")

    chunks_needed = max(1, math.ceil(lookback_hours / 168))
    target_timestamps = ts_list[-chunks_needed:]
    all_series = []
    for ts in target_timestamps:
        chunk_url = SMARD_CHUNK_TEMPLATE.format(ts=ts)
        chunk_resp = requests.get(chunk_url, timeout=30)
        chunk_resp.raise_for_status()
        all_series.extend(chunk_resp.json().get("series", []))

    df = _parse_smard_json({"series": all_series})
    cutoff = df.index.max() - pd.Timedelta(hours=lookback_hours)
    return df[df.index >= cutoff]


def _parse_smard_json(raw: dict) -> pd.DataFrame:
    """
    Parse SMARD JSON response into a UTC-indexed DataFrame.
    SMARD returns timestamps as Unix epoch milliseconds.
    """
    series = raw.get("series", [])
    records = []
    for ts_ms, value in series:
        if value is None:
            continue
        records.append(
            {
                "timestamp": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
                "solar_generation_mw": float(value),
            }
        )
    df = pd.DataFrame(records).set_index("timestamp").sort_index()
    # INV-001: enforce physical non-negativity immediately
    df["solar_generation_mw"] = df["solar_generation_mw"].clip(lower=0.0)
    logger.info(
        "Parsed %d SMARD records (%.1f – %.1f MW range)",
        len(df),
        df["solar_generation_mw"].min(),
        df["solar_generation_mw"].max(),
    )
    return df


def _engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add cyclical time-of-day and day-of-year features plus lag/rolling features.
    All features are computed purely from the DatetimeIndex — no data leakage.
    """
    df = df.copy()
    hours = df.index.hour + df.index.minute / 60.0
    doy = df.index.dayofyear

    # Cyclical encodings
    df["hour_sin"] = np.sin(2 * math.pi * hours / 24.0)
    df["hour_cos"] = np.cos(2 * math.pi * hours / 24.0)
    df["doy_sin"] = np.sin(2 * math.pi * doy / 365.25)
    df["doy_cos"] = np.cos(2 * math.pi * doy / 365.25)

    # Lag features (15-min intervals: 4 steps = 1 h, 96 steps = 24 h)
    df["lag_1h"] = df["solar_generation_mw"].shift(4).clip(lower=0.0)
    df["lag_24h"] = df["solar_generation_mw"].shift(96).clip(lower=0.0)

    # Rolling statistics (3 h = 12 steps, min_periods=1 to avoid excessive NaN)
    df["rolling_mean_3h"] = (
        df["solar_generation_mw"].rolling(12, min_periods=1).mean().clip(lower=0.0)
    )
    df["rolling_std_3h"] = (
        df["solar_generation_mw"].rolling(12, min_periods=1).std().fillna(0.0)
    )

    return df.dropna()


FEATURE_COLS = [
    "hour_sin", "hour_cos",
    "doy_sin", "doy_cos",
    "lag_1h", "lag_24h",
    "rolling_mean_3h", "rolling_std_3h",
]
TARGET_COL = "solar_generation_mw"


# ---------------------------------------------------------------------------
# Forecasting strategies
# ---------------------------------------------------------------------------


def _forecast_ma_baseline(df: pd.DataFrame) -> tuple[float, float, float]:
    """
    Moving-average baseline: 1-hour (4 × 15 min) rolling mean.
    Returns (q10, q50, q90) as (mean - std, mean, mean + std).
    """
    window = df[TARGET_COL].tail(4)
    mean = float(window.mean())
    std = float(window.std()) if len(window) > 1 else 0.0
    q10 = max(0.0, mean - 1.282 * std)
    q50 = max(0.0, mean)
    q90 = max(0.0, mean + 1.282 * std)
    return q10, q50, q90


def _forecast_lightgbm(df: pd.DataFrame) -> tuple[float, float, float]:
    """
    Train three LightGBM quantile regressors (q=0.10, 0.50, 0.90)
    using time-series cross-validation, then predict the next step.

    Uses the last 80 % of data for training; 20 % for validation.
    """
    from sklearn.model_selection import TimeSeriesSplit  # type: ignore

    df_feat = _engineer_features(df)
    if len(df_feat) < 96:
        logger.warning(
            "Insufficient data for LightGBM (%d rows). Falling back to MA.",
            len(df_feat),
        )
        return _forecast_ma_baseline(df)

    X = df_feat[FEATURE_COLS].values
    y = df_feat[TARGET_COL].values

    split = int(len(X) * 0.8)
    X_train, y_train = X[:split], y[:split]

    predictions: dict[float, float] = {}
    for alpha in (0.10, 0.50, 0.90):
        model = lgb.LGBMRegressor(
            objective="quantile",
            alpha=alpha,
            num_leaves=63,
            learning_rate=0.05,
            n_estimators=300,
            verbose=-1,
        )
        model.fit(X_train, y_train)

        # Predict next step using last available feature row
        X_next = df_feat[FEATURE_COLS].iloc[[-1]].values
        pred = float(model.predict(X_next)[0])
        predictions[alpha] = max(0.0, pred)  # INV-002

    q10, q50, q90 = predictions[0.10], predictions[0.50], predictions[0.90]

    # Ensure ordering — occasionally quantile regression can cross
    q10 = min(q10, q50)
    q90 = max(q90, q50)

    logger.info(
        "LightGBM forecast: q10=%.2f  q50=%.2f  q90=%.2f MW", q10, q50, q90
    )
    return q10, q50, q90


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run(
    mode: str = "fixture",
    fixture_path: Optional[Path] = None,
    lookback_hours: int = 720,  # ~30 days
    use_lightgbm: bool = True,
) -> dict:
    """
    Module 1 entry point.

    Args:
        mode:           "fixture" (offline) or "live" (SMARD REST API).
        fixture_path:   Path to fixture JSON; defaults to tests/fixtures/smard_30d.json.
        lookback_hours: Lookback window for live mode.
        use_lightgbm:   If True and lightgbm is available, use LightGBM; else MA.

    Returns:
        ForecastOutput as a dict (validated Pydantic model).
    """
    # Import here to respect the rule that contracts are the boundary contract
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from libs.contracts.telemetry import ForecastOutput

    # 1. Load data
    if mode == "fixture":
        fp = fixture_path or FIXTURE_PATH_DEFAULT
        df = _load_fixture(fp)
    elif mode == "live":
        df = _fetch_live(lookback_hours=lookback_hours)
    else:
        raise ValueError(f"Unknown mode '{mode}'. Use 'fixture' or 'live'.")

    training_start = df.index.min().to_pydatetime()
    training_end = df.index.max().to_pydatetime()
    forecast_ts = training_end  # next-step horizon

    # 2. Forecast
    if use_lightgbm and _LGB_AVAILABLE:
        q10, q50, q90 = _forecast_lightgbm(df)
        model_version: str = "LightGBM-v1"
    else:
        q10, q50, q90 = _forecast_ma_baseline(df)
        model_version = "MA-baseline"

    # 3. Build & validate output via Pydantic contract
    output = ForecastOutput(
        timestamp=forecast_ts,
        predicted_solar_mw=q50,
        quantile_10_mw=q10,
        quantile_90_mw=q90,
        model_version=model_version,  # type: ignore[arg-type]
        training_data_start=training_start,
        training_data_end=training_end,
    )

    logger.info(
        "Module 1 complete: predicted=%.2f MW  [%.2f, %.2f]  model=%s",
        output.predicted_solar_mw,
        output.quantile_10_mw,
        output.quantile_90_mw,
        output.model_version,
    )
    return output.model_dump()
