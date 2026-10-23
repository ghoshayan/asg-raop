"""
pipeline.py — ASG-RAOP End-to-End Integration Orchestrator
===========================================================
Wires all four modules together in the correct dependency order:

  Module 1 (Forecast) → Module 2 (Vision) → Module 3 (Grid Physics)
      → Module 4 (Copilot, conditional on redispatch_required)

Usage:
  python pipeline.py                      # offline fixture mode, simbench-mv-rural
  python pipeline.py --mode live          # live SMARD data
  python pipeline.py --topology example-mv
  python pipeline.py --no-copilot        # skip Module 4 (no Gemini key needed)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Logging setup — must happen before any module import
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("pipeline")

# ---------------------------------------------------------------------------
# Resolve project root so modules & libs are importable regardless of CWD
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Module imports
# ---------------------------------------------------------------------------
import modules  # noqa: E402 — ensures package __init__.py is loaded


import importlib

_forecast_mod = importlib.import_module("modules.01_forecast")
_vision_mod = importlib.import_module("modules.02_vision")
_grid_mod = importlib.import_module("modules.03_grid_physics")
_copilot_mod = importlib.import_module("modules.04_copilot")


# ---------------------------------------------------------------------------
# Core pipeline function
# ---------------------------------------------------------------------------


def run_pipeline(
    smard_mode: str = "fixture",
    smard_fixture_path: Optional[Path] = None,
    smard_lookback_hours: int = 720,
    asset_id: str = "PV-ASSET-001",
    asset_image_path: Optional[Path] = None,
    onnx_model_path: Optional[Path] = None,
    topology_name: str = "simbench-mv-rural",
    run_n1: bool = True,
    use_lightgbm: bool = True,
    enable_copilot: bool = True,
    gemini_api_key: Optional[str] = None,
) -> dict:
    """
    Execute the full ASG-RAOP pipeline.

    Returns a dict containing validated outputs from all four modules.
    Copilot output is None if enable_copilot=False or redispatch_required=False.
    """
    t_start = time.monotonic()
    logger.info("=" * 60)
    logger.info("ASG-RAOP Pipeline START  [mode=%s  topology=%s]", smard_mode, topology_name)
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Module 1: Temporal Forecaster
    # ------------------------------------------------------------------
    logger.info("--- Module 1: Temporal Forecaster ---")
    forecast: dict = _forecast_mod.run(
        mode=smard_mode,
        fixture_path=smard_fixture_path,
        lookback_hours=smard_lookback_hours,
        use_lightgbm=use_lightgbm,
    )
    logger.info(
        "  → predicted=%.2f MW  [q10=%.2f, q90=%.2f]  model=%s",
        forecast["predicted_solar_mw"],
        forecast["quantile_10_mw"],
        forecast["quantile_90_mw"],
        forecast["model_version"],
    )

    # ------------------------------------------------------------------
    # Module 2: Computer Vision Asset Inspector
    # ------------------------------------------------------------------
    logger.info("--- Module 2: Vision Asset Inspector ---")
    degradation: dict = _vision_mod.run(
        predicted_solar_mw=forecast["predicted_solar_mw"],
        asset_id=asset_id,
        image_path=asset_image_path,
        onnx_model_path=onnx_model_path,
    )
    logger.info(
        "  → D_pv=%.4f  P_effective=%.2f MW  confidence=%.3f",
        degradation["degradation_scalar"],
        degradation["effective_solar_mw"],
        degradation["confidence"],
    )

    # ------------------------------------------------------------------
    # Module 3: Physical Grid Simulator
    # ------------------------------------------------------------------
    logger.info("--- Module 3: Physical Grid Simulator ---")
    powerflow: dict = _grid_mod.run(
        effective_solar_mw=degradation["effective_solar_mw"],
        topology_name=topology_name,
        run_n1=run_n1,
    )
    logger.info(
        "  → overloaded=%s  max_loading=%.1f %%  V=[%.3f, %.3f] p.u.  redispatch=%s",
        powerflow["is_overloaded"],
        powerflow["max_line_loading_pct"],
        powerflow["min_bus_voltage_pu"],
        powerflow["max_bus_voltage_pu"],
        powerflow["redispatch_required"],
    )

    # ------------------------------------------------------------------
    # Module 4: Agentic Copilot (conditional)
    # ------------------------------------------------------------------
    copilot: Optional[dict] = None
    if enable_copilot and powerflow["redispatch_required"]:
        logger.info("--- Module 4: Agentic Copilot (Redispatch 2.0) ---")
        copilot = _copilot_mod.run(
            forecast=forecast,
            degradation=degradation,
            powerflow=powerflow,
            gemini_api_key=gemini_api_key,
        )
        logger.info(
            "  → proposals=%d  redispatch_volume=%.2f MW  scada_blocked=%s",
            len(copilot["proposals"]),
            copilot["redispatch_volume_mw"],
            copilot["scada_write_blocked"],
        )
    elif not powerflow["redispatch_required"]:
        logger.info("--- Module 4: SKIPPED (no redispatch condition) ---")
    else:
        logger.info("--- Module 4: DISABLED by flag ---")

    elapsed = time.monotonic() - t_start
    logger.info("=" * 60)
    logger.info("ASG-RAOP Pipeline COMPLETE  [%.2f s]", elapsed)
    logger.info("=" * 60)

    return {
        "forecast": forecast,
        "degradation": degradation,
        "powerflow": powerflow,
        "copilot": copilot,
        "elapsed_seconds": round(elapsed, 3),
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="ASG-RAOP End-to-End Pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--mode", choices=["fixture", "live"], default="fixture",
        help="SMARD data source mode."
    )
    p.add_argument(
        "--topology",
        choices=["simbench-mv-rural", "simbench-mv-urban", "simbench-hv", "example-mv"],
        default="example-mv",
        help="SimBench network topology."
    )
    p.add_argument(
        "--no-lightgbm", action="store_true",
        help="Use Moving Average baseline instead of LightGBM."
    )
    p.add_argument(
        "--no-n1", action="store_true",
        help="Skip N-1 contingency analysis (faster)."
    )
    p.add_argument(
        "--no-copilot", action="store_true",
        help="Skip Module 4 (no Gemini API key required)."
    )
    p.add_argument(
        "--asset-id", default="PV-ASSET-001",
        help="PV asset identifier."
    )
    p.add_argument(
        "--image-path", type=Path, default=None,
        help="Path to solar cell EL image for defect analysis."
    )
    return p


if __name__ == "__main__":
    args = _build_parser().parse_args()
    result = run_pipeline(
        smard_mode=args.mode,
        topology_name=args.topology,
        use_lightgbm=not args.no_lightgbm,
        run_n1=not args.no_n1,
        enable_copilot=not args.no_copilot,
        asset_id=args.asset_id,
        asset_image_path=args.image_path,
    )
    print("\n--- Pipeline Summary ---")
    print(json.dumps(result, default=str, indent=2))
