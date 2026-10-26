# ASG-RAOP — Autonomous Smart Grid & Renewable Asset Orchestration Platform

[![CI](https://github.com/ghoshayan/asg-raop/actions/workflows/ci.yml/badge.svg)](https://github.com/ghoshayan/asg-raop/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

> **Status:** Active Development — Modular Monolith ("Tracer Bullet") phase.

## Overview

ASG-RAOP is an applied multi-modal data-science and energy-engineering system that
simulates, forecasts, inspects, and optimises decentralised renewable power systems
under German regulatory conditions (BNetzA Redispatch 2.0, EnWG §13, EU AI Act).

## Architecture

```
DATA INGESTION (SMARD.de Filter 1226 — 15-min Solar DE)
        │
        ▼
MODULE 1 — TEMPORAL FORECASTER          (01_forecast.py)
  LightGBM Quantile Regression (q=0.10/0.50/0.90)
        │  {"predicted_solar_mw", "quantile_10_mw", "quantile_90_mw"}
        ▼
MODULE 2 — COMPUTER VISION ASSET INSPECTOR  (02_vision.py)
  ONNX Runtime defect mask → D_pv ∈ [0,1]
  P_effective = P_forecast × (1 − D_pv)
        │  {"effective_solar_mw", "degradation_scalar"}
        ▼
MODULE 3 — PHYSICAL GRID SIMULATOR      (03_grid_physics.py)
  pandapower AC Newton-Raphson load-flow on SimBench MV topology
  Evaluates line thermal limits & bus voltages (EN 50160)
        │  {"is_overloaded", "redispatch_required", "critical_lines"}
        ▼
MODULE 4 — AGENTIC COPILOT              (04_copilot.py)
  Gemini 2.5 Flash — BNetzA Redispatch 2.0 rule engine
  Human-in-the-loop gatekeeper (SCADA write blocked without approval)
```

## Quick Start

```powershell
# 1. Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run Google-SWE presubmit gate (tests + secrets + smoke test)
python scripts/presubmit.py

# 4. Run end-to-end pipeline (offline fixture mode)
python pipeline.py

# 5. Run end-to-end pipeline with solar cell EL defect image
python pipeline.py --image-path tests/fixtures/elpv_samples/microcrack_cell.png

# 6. Fetch full open datasets (D4 FAU ELPV & D5 OPSD Parquet)
python scripts/bootstrap_data.py

# 7. Launch Interactive Operator Web Cockpit
python scripts/run_dashboard.py
# Open http://localhost:8000 in your browser
```

## Regulatory Compliance

| Framework | Scope |
|---|---|
| **BNetzA Redispatch 2.0** | Congestion management, curtailment proposals |
| **EnWG §13** | Legal basis for grid operator interventions |
| **EU AI Act Article 6(3) & 14** | Advisory-only ML, strict human-in-the-loop SCADA isolation |
| **EN 50160** | Voltage quality: bus voltages must stay in [0.85, 1.15] p.u. |

## Module Status

| Module | File | Status | Model / Provider |
|---|---|---|---|
| 01 Temporal Forecaster | `modules/01_forecast.py` | ✅ Active | LightGBM quantile regression (`q10`, `q50`, `q90`) |
| 02 Vision Inspector | `modules/02_vision.py` | ✅ Active | Pure-Python EL image contrast & defect scoring |
| 03 Grid Simulator | `modules/03_grid_physics.py` | ✅ Active | Pandapower AC Newton-Raphson + N-1 contingency |
| 04 Agentic Copilot | `modules/04_copilot.py` | ✅ Active | EnWG §13 rule gate & Gemini 2.5 Flash copilot |

## Directory Layout

```
energy_lab/
├── .github/              # GitHub Actions CI workflow & PR template
├── libs/contracts/       # Canonical Pydantic v2 data contracts
├── modules/              # Core business modules (one responsibility per file)
├── scripts/              # Presubmit gatekeeper & automated data bootstrapping
├── tests/fixtures/       # Offline sample EL images & SMARD 30-day baseline
├── ANTIGRAVITY.md        # Complete system blueprint & architectural specs
├── pipeline.py           # End-to-end pipeline orchestrator
├── test_pipeline.py      # 21-invariant physical & regulatory verification suite
├── pyproject.toml        # Ruff, pytest, and project build configuration
└── requirements.txt      # Pinned core production dependencies
```
