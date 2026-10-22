"""
libs/contracts/telemetry.py

Pydantic v2 data contracts for Module 1 — Temporal Forecaster.
Covers SMARD API records and LightGBM quantile forecast output.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class SMARDRecord(BaseModel):
    """
    A single 15-minute SMARD.de solar generation observation.

    Physical invariant INV-001: solar_generation_mw >= 0.0.
    """

    timestamp: datetime = Field(..., description="UTC timestamp of the observation")
    solar_generation_mw: float = Field(
        ..., description="Observed solar generation in megawatts"
    )

    @field_validator("solar_generation_mw")
    @classmethod
    def enforce_non_negativity(cls, v: float) -> float:
        """INV-001: Physical non-negativity of solar generation."""
        if v < 0.0:
            raise ValueError(
                f"solar_generation_mw must be >= 0.0 (got {v}). "
                "Apply .clip(lower=0.0) before constructing this model."
            )
        return v


class ForecastOutput(BaseModel):
    """
    Output contract for Module 1 (01_forecast.py).

    Carries the point forecast (median) plus 80 % prediction interval
    from LightGBM quantile regression (q=0.10, 0.50, 0.90).

    Physical invariants: INV-002, INV-003.
    EU AI Act: model_version + training_data_range required (Article 13).
    """

    timestamp: datetime = Field(..., description="Forecast horizon timestamp (UTC)")
    predicted_solar_mw: float = Field(
        ..., ge=0.0, description="Median forecast (q=0.50) in MW"
    )
    quantile_10_mw: float = Field(
        ..., ge=0.0, description="10th-percentile lower bound in MW"
    )
    quantile_90_mw: float = Field(
        ..., ge=0.0, description="90th-percentile upper bound in MW"
    )
    model_version: Literal["MA-baseline", "LightGBM-v1"] = Field(
        ..., description="Model identifier for EU AI Act audit trail"
    )
    training_data_start: datetime = Field(
        ..., description="Start of training window (EU AI Act Article 13)"
    )
    training_data_end: datetime = Field(
        ..., description="End of training window (EU AI Act Article 13)"
    )

    @model_validator(mode="after")
    def enforce_quantile_ordering(self) -> ForecastOutput:
        """INV-003: quantile_10 <= predicted (q50) <= quantile_90."""
        if not (self.quantile_10_mw <= self.predicted_solar_mw <= self.quantile_90_mw):
            raise ValueError(
                f"Quantile ordering violated: "
                f"q10={self.quantile_10_mw} <= q50={self.predicted_solar_mw} "
                f"<= q90={self.quantile_90_mw} must hold."
            )
        return self
