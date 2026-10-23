"""
modules/04_copilot.py — Agentic Copilot & Human-in-the-Loop Gatekeeper
========================================================================
Module 4 of the ASG-RAOP pipeline.

Responsibilities:
  1. Receive the full pipeline state (forecast + degradation + powerflow).
  2. Evaluate grid contingency against BNetzA Redispatch 2.0 rules.
  3. Call Gemini 2.5 Flash to synthesise an operational incident log
     and generate structured curtailment proposals with EnWG legal citations.
  4. Enforce the Human-in-the-Loop gatekeeper:
       SCADA write is unconditionally blocked unless operator_approved == True
       AND approving_operator_id is set.  (INV-009)
  5. Write the full incident record to data/logs/incidents.jsonl.
  6. Return a validated CopilotOutput Pydantic model.

Regulatory invariants:
  INV-009: SCADA write blocked when operator_approved == False
  INV-010: legal_basis non-empty in every CurtailmentProposal

EU AI Act compliance:
  - All proposals logged before human review (Rule EU-04)
  - Model version recorded in every log entry (Rule EU-02)
  - Gemini reasoning captured verbatim for audit trail (Rule EU-05)

Public API:
    run(forecast: dict, degradation: dict, powerflow: dict,
        gemini_api_key: Optional[str]) -> dict
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import — Gemini SDK
# ---------------------------------------------------------------------------
try:
    from google import genai  # type: ignore
    from google.genai import types as genai_types  # type: ignore

    _GENAI_AVAILABLE = True
except ImportError:
    _GENAI_AVAILABLE = False
    logger.warning(
        "google-genai not installed — copilot will use deterministic stub."
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MODEL_ID = "gemini-2.5-flash"
LOG_PATH = Path(__file__).parent.parent / "data" / "logs" / "incidents.jsonl"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

_SYSTEM_PROMPT = """\
You are ASG-RAOP Copilot, an expert energy-grid operational assistant.

REGULATORY CONTEXT:
- You operate under BNetzA Redispatch 2.0 (§ 13 EnWG).
- All curtailment proposals must cite the specific EnWG paragraph.
- You are advisory-only: no action is taken without human operator approval.
- You must be transparent about uncertainty.

TASK:
Given a grid contingency report, produce:
1. A concise incident summary (≤ 150 words) explaining the technical situation.
2. A JSON block containing structured curtailment proposals.

PROPOSAL JSON FORMAT (return this exact structure):
{
  "proposals": [
    {
      "asset_id": "<string>",
      "curtailment_mw": <float ≥ 0>,
      "legal_basis": "<e.g. EnWG §13 Abs. 1>"
    }
  ],
  "redispatch_volume_mw": <float ≥ 0>,
  "incident_summary": "<≤ 150 word plain-text summary>"
}

Return ONLY the JSON block — no markdown fences, no additional text.
"""


# ---------------------------------------------------------------------------
# Gemini API call
# ---------------------------------------------------------------------------


def _call_gemini(
    forecast: dict,
    degradation: dict,
    powerflow: dict,
    api_key: str,
) -> dict:
    """
    Build a context prompt from pipeline state and call Gemini 2.5 Flash.
    Returns the parsed JSON proposal dict.
    """
    client = genai.Client(api_key=api_key)

    user_message = f"""
GRID CONTINGENCY REPORT
=======================
Timestamp           : {datetime.now(tz=timezone.utc).isoformat()}
Forecast (Module 1) : {json.dumps(forecast, default=str, indent=2)}
Degradation (M2)    : {json.dumps(degradation, default=str, indent=2)}
Power Flow (M3)     : {json.dumps(powerflow, default=str, indent=2)}

Key indicators:
  - Redispatch required   : {powerflow.get('redispatch_required')}
  - Max line loading      : {powerflow.get('max_line_loading_pct', 0):.1f} %
  - Critical lines        : {powerflow.get('critical_lines', [])}
  - Min bus voltage       : {powerflow.get('min_bus_voltage_pu', 1.0):.4f} p.u.
  - Asset degradation     : {degradation.get('degradation_scalar', 0):.4f}
  - Effective solar       : {degradation.get('effective_solar_mw', 0):.2f} MW

Generate a BNetzA Redispatch 2.0 curtailment proposal.
"""

    response = client.models.generate_content(
        model=MODEL_ID,
        contents=user_message,
        config=genai_types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            temperature=0.2,
            max_output_tokens=1024,
        ),
    )

    raw_text = response.text.strip()
    logger.debug("Gemini raw response: %s", raw_text)

    # Strip markdown fences if the model wraps in ```json
    if raw_text.startswith("```"):
        raw_text = "\n".join(raw_text.split("\n")[1:-1])

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Gemini returned non-JSON output: {raw_text[:200]}"
        ) from exc


# ---------------------------------------------------------------------------
# Deterministic stub (no Gemini API key / SDK)
# ---------------------------------------------------------------------------


def _stub_response(powerflow: dict, degradation: dict) -> dict:
    """
    Rule-based stub that generates a plausible proposal without calling Gemini.
    Used for offline development and CI environments without API keys.
    """
    logger.info("Using deterministic copilot stub (no Gemini API key).")
    max_loading = powerflow.get("max_line_loading_pct", 0.0)
    effective_mw = degradation.get("effective_solar_mw", 0.0)
    asset_id = degradation.get("asset_id", "PV-ASSET-001")

    # Curtail proportional to overload severity
    overload_fraction = max(0.0, (max_loading - 80.0) / 100.0)
    curtailment_mw = round(effective_mw * overload_fraction, 2)

    return {
        "proposals": [
            {
                "asset_id": asset_id,
                "curtailment_mw": curtailment_mw,
                "legal_basis": "EnWG §13 Abs. 1",
            }
        ],
        "redispatch_volume_mw": curtailment_mw,
        "incident_summary": (
            f"Grid contingency detected: line loading at {max_loading:.1f} % "
            f"exceeds the 80 % thermal limit. Asset {asset_id} is generating "
            f"{effective_mw:.2f} MW (D_pv={degradation.get('degradation_scalar', 0):.4f}). "
            f"Proposed curtailment of {curtailment_mw:.2f} MW under EnWG §13 Abs. 1. "
            "Awaiting operator approval before any SCADA action."
        ),
    }


# ---------------------------------------------------------------------------
# Incident logging
# ---------------------------------------------------------------------------


def _write_incident_log(
    incident_id: str,
    forecast: dict,
    degradation: dict,
    powerflow: dict,
    proposals_raw: list[dict],
    redispatch_volume_mw: float,
    incident_summary: str,
    model_version: str,
) -> None:
    """Append an audit log entry to incidents.jsonl (EU AI Act Rule EU-04)."""
    entry = {
        "incident_id": incident_id,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "module": "04_copilot",
        "model_version": model_version,
        "grid_state": {
            "is_overloaded": powerflow.get("is_overloaded"),
            "max_line_loading_pct": powerflow.get("max_line_loading_pct"),
            "redispatch_required": powerflow.get("redispatch_required"),
            "min_bus_voltage_pu": powerflow.get("min_bus_voltage_pu"),
        },
        "degradation": {
            "asset_id": degradation.get("asset_id"),
            "degradation_scalar": degradation.get("degradation_scalar"),
            "effective_solar_mw": degradation.get("effective_solar_mw"),
        },
        "forecast": {
            "predicted_solar_mw": forecast.get("predicted_solar_mw"),
            "model_version": forecast.get("model_version"),
        },
        "proposals": proposals_raw,
        "redispatch_volume_mw": redispatch_volume_mw,
        "incident_summary": incident_summary,
        "operator_approved": False,          # always False at generation time
        "scada_write_blocked": True,         # always True at generation time
    }

    with open(LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    logger.info("Incident %s written to %s", incident_id, LOG_PATH)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run(
    forecast: dict,
    degradation: dict,
    powerflow: dict,
    gemini_api_key: Optional[str] = None,
) -> dict:
    """
    Module 4 entry point.

    Args:
        forecast:        ForecastOutput dict from Module 1.
        degradation:     DegradationOutput dict from Module 2.
        powerflow:       PowerFlowOutput dict from Module 3.
        gemini_api_key:  Gemini API key (falls back to GEMINI_API_KEY env var,
                         then to deterministic stub).

    Returns:
        CopilotOutput as a dict (validated Pydantic model).
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from libs.contracts.powerflow import CopilotOutput, CurtailmentProposal

    incident_id = str(uuid.uuid4())
    model_version = MODEL_ID

    # --- Resolve API key ---
    api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY", "")

    # --- Generate proposals ---
    if _GENAI_AVAILABLE and api_key:
        try:
            response_json = _call_gemini(forecast, degradation, powerflow, api_key)
        except Exception as exc:
            logger.warning(
                "Gemini API call failed (%s). Using deterministic stub.", exc
            )
            response_json = _stub_response(powerflow, degradation)
            model_version = "stub-v1"
    else:
        response_json = _stub_response(powerflow, degradation)
        model_version = "stub-v1"

    proposals_raw: list[dict] = response_json.get("proposals", [])
    redispatch_volume_mw: float = float(response_json.get("redispatch_volume_mw", 0.0))
    incident_summary: str = response_json.get("incident_summary", "")

    # --- Build CurtailmentProposal objects (INV-009, INV-010 validated) ---
    proposals: list[CurtailmentProposal] = []
    for p in proposals_raw:
        cp = CurtailmentProposal(
            asset_id=p.get("asset_id", degradation.get("asset_id", "UNKNOWN")),
            curtailment_mw=max(0.0, float(p.get("curtailment_mw", 0.0))),
            legal_basis=p.get("legal_basis", "EnWG §13 Abs. 1"),
            operator_approved=False,    # always False at generation time (INV-009)
            gemini_reasoning=incident_summary,
        )
        proposals.append(cp)

    # --- Write immutable audit log (EU AI Act Rule EU-04) ---
    _write_incident_log(
        incident_id=incident_id,
        forecast=forecast,
        degradation=degradation,
        powerflow=powerflow,
        proposals_raw=proposals_raw,
        redispatch_volume_mw=redispatch_volume_mw,
        incident_summary=incident_summary,
        model_version=model_version,
    )

    # --- Console output (D6 decision: log file + console) ---
    print(f"\n{'='*60}")
    print(f"  ASG-RAOP INCIDENT REPORT  [{incident_id[:8]}]")
    print(f"{'='*60}")
    print(f"  Model      : {model_version}")
    print(f"  Summary    : {incident_summary[:200]}")
    print(f"  Proposals  :")
    for prop in proposals:
        print(
            f"    - Asset: {prop.asset_id}  |  "
            f"Curtail: {prop.curtailment_mw:.2f} MW  |  "
            f"Legal: {prop.legal_basis}"
        )
    print(f"  SCADA write: BLOCKED (awaiting operator approval)")
    print(f"{'='*60}\n")

    # --- Build CopilotOutput ---
    output = CopilotOutput(
        incident_id=incident_id,
        generated_at=datetime.now(tz=timezone.utc),
        model_version=model_version,
        proposals=proposals,
        incident_summary=incident_summary,
        redispatch_volume_mw=redispatch_volume_mw,
        scada_write_blocked=True,   # always True at generation time
    )

    logger.info(
        "Module 4 complete: incident=%s  proposals=%d  redispatch=%.2f MW  "
        "scada_blocked=%s",
        incident_id,
        len(output.proposals),
        output.redispatch_volume_mw,
        output.scada_write_blocked,
    )
    return output.model_dump()
