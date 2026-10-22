"""
libs/contracts/degradation.py

Pydantic v2 data contracts for Module 2 — Computer Vision Asset Inspector.
Covers ELPV EL-image input records and degradation scalar output.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class ELImageRecord(BaseModel):
    """
    Input descriptor for a single Electroluminescence (EL) image capture.
    """

    asset_id: str = Field(..., description="Unique identifier of the PV asset")
    image_path: Path = Field(..., description="Absolute path to the EL image file")
    capture_timestamp: datetime = Field(
        ..., description="UTC timestamp of the EL capture"
    )


class DegradationOutput(BaseModel):
    """
    Output contract for Module 2 (02_vision.py).

    Physical invariants: INV-004, INV-005, INV-006.

    D_pv ∈ [0.0, 1.0] where:
      0.0 = pristine (no defects detected)
      1.0 = fully degraded (no effective generation)
    """

    asset_id: str = Field(..., description="PV asset identifier")
    degradation_scalar: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="D_pv ∈ [0.0, 1.0] — fraction of capacity lost to defects",
    )
    defect_mask_path: Optional[Path] = Field(
        default=None,
        description="Path to saved pixel-wise defect probability mask (PNG)",
    )
    effective_solar_mw: float = Field(
        ...,
        ge=0.0,
        description="P_effective = P_forecast × (1 − D_pv) in MW",
    )
    predicted_solar_mw: float = Field(
        ...,
        ge=0.0,
        description="Upstream P_forecast used for effective power computation",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="ONNX model confidence (max softmax probability)",
    )
    model_version: str = Field(
        default="ONNX-stub-v0",
        description="ONNX model identifier for EU AI Act audit trail",
    )

    @model_validator(mode="after")
    def enforce_degradation_reduces_output(self) -> DegradationOutput:
        """
        INV-005: effective_solar_mw <= predicted_solar_mw.
        Degradation can only reduce, never increase, available generation.
        Allow a small floating-point epsilon for numerical precision.
        """
        eps = 1e-6
        if self.effective_solar_mw > self.predicted_solar_mw + eps:
            raise ValueError(
                f"effective_solar_mw ({self.effective_solar_mw:.4f}) must be <= "
                f"predicted_solar_mw ({self.predicted_solar_mw:.4f}). "
                "Degradation can only reduce available generation."
            )
        return self
