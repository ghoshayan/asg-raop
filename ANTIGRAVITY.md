# ANTIGRAVITY.md — Project Blueprint & Operational Guide

**Project:** Autonomous Smart Grid & Renewable Asset Orchestration Platform (ASG-RAOP)  
**Root Directory:** `energy_lab/`  
**Execution Environment:** Antigravity IDE (Local Python 3.11+ Virtual Environment)

---

## 1. System Architecture & Engineering Principles

The ASG-RAOP project follows a **Modular Monolith ("Tracer Bullet")** architecture. Subsystems are built as isolated, single-responsibility Python modules inside `modules/`. Data flows downstream through strongly typed dictionaries and Pydantic schemas, eliminating the overhead of microservices, networking layers, and message queues during initial engineering while preserving clean boundaries for containerization with Docker Compose when scaling.

```
 [SMARD.de REST API / OPSD Baseline]
                  │
                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ MODULE 01: TEMPORAL FORECASTER                                          │
│ - Ingests 15-min German grid solar generation (Filter 1226)             │
│ - Enforces physical non-negativity constraint: P_solar >= 0.0           │
│ - Upgrades: 3-period Moving Average -> LightGBM Quantile Regression     │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ {"timestamp": "...", "predicted_solar_mw": 50.0}
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ MODULE 02: ASSET COMPUTER VISION                                        │
│ - Evaluates solar cell Electroluminescence (EL) imagery via ONNX/PIL    │
│ - Computes degradation scalar D_pv in [0.0, 1.0]                        │
│ - Applies asset derating: P_effective = P_predicted * (1 - D_pv)        │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ {"effective_solar_mw": 42.5, "degradation_factor": 0.15}
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ MODULE 03: PHYSICAL GRID SIMULATOR                                      │
│ - Loads SimBench German medium-voltage commercial network               │
│ - Solves non-linear AC Newton-Raphson power flow (pandapower)           │
│ - Evaluates line thermal limits (% loading) & bus voltages (p.u.)       │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ {"is_overloaded": True, "line_loading_pct": 105.2}
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ MODULE 04: AGENTIC COPILOT & REGULATORY GATEWAY                         │
│ - Benchmarks grid state against BNetzA Redispatch 2.0 / EnWG §13        │
│ - Synthesizes curtailment orders and operational logs via Gemini API    │
│ - EU AI Act Gate: Rejects actuation without verified operator token     │
└─────────────────────────────────────────────────────────────────────────┘
```

### Regulatory Governance: EU AI Act Compliance
Under **Annex III, Point 2 of Regulation (EU) 2024/1689 (EU AI Act)**, AI systems operating safety components in critical electrical infrastructure are classified as High-Risk.

The platform implements the **Decision Support System (DSS) Isolation Pattern (Article 6(3))**:
* All machine learning models operate strictly in an advisory capacity.
* Closed-loop actuation to physical switchgear or SCADA interfaces is blocked at the code level.
* Every recommendation requires an explicit cryptographic authorization token (`operator_jwt` / `approving_operator_id`) issued by a certified human grid operator (Article 14).

---

## 2. Antigravity IDE Workspace Scaffolding

```text
energy_lab/
├── ANTIGRAVITY.md               # Master blueprint & operational guide
├── README.md                    # Project overview
├── requirements.txt             # Project dependencies (LightGBM, Pandapower, SimBench, etc.)
├── pipeline.py                  # End-to-end integration orchestrator
├── test_pipeline.py             # Automated verification & invariant test suite
├── conftest.py                  # Pytest fixtures & auto-generator for SMARD 30-day baseline
├── .gitignore                   # Ignores large raw caches, .venv, *.parquet, *.onnx
├── .agents/                     # Antigravity agent configuration
│   ├── rules/
│   │   ├── 01-architecture-contracts.md   # Decoupling & typing invariants
│   │   ├── 02-eu-ai-act-guardrails.md     # Advisory-only execution constraints
│   │   └── 03-testing-invariants.md       # Physical assertion mandates
│   └── workflows/
│       └── test-e2e.md                    # Slash-command test workflow
├── libs/
│   └── contracts/               # Shared Pydantic data schemas
│       ├── __init__.py
│       ├── telemetry.py         # SMARDRecord, ForecastOutput
│       ├── degradation.py       # DegradationMetric, DegradationOutput
│       └── powerflow.py         # PowerFlowOutput, CurtailmentProposal, CopilotOutput
├── modules/
│   ├── __init__.py
│   ├── 01_forecast.py           # Ingestion & solar quantile forecasting
│   ├── 02_vision.py             # Asset degradation via EL image inference
│   ├── 03_grid_physics.py       # SimBench AC Newton-Raphson power flow solver
│   └── 04_copilot.py            # Gemini API Redispatch 2.0 assistant & SCADA gatekeeper
├── scripts/
│   └── bootstrap_data.py        # Automated D4 (ELPV) & D5 (OPSD) zero-manual fetcher
├── data/                        # Local raw data cache (git-ignored)
│   ├── smard/                   # SMARD.de market/generation dumps
│   ├── elpv/                    # FAU solar cell EL imagery
│   ├── opsd/                    # OPSD historical weather & solar Parquet slices
│   └── logs/                    # Audit & incident logs (incidents.jsonl)
└── tests/
    └── fixtures/                # Committed fast fixtures (< 50ms offline test execution)
        ├── smard_30d.json       # 30-day synthetic SMARD 15-min baseline
        └── elpv_samples/        # 4 representative PV cell sample images
```

---

## 3. Data Ingestion & Data Sourcing Matrix

| Code | Dataset Name | Domain / Purpose | Local Footprint | Fetch Method | Local Path |
|---|---|---|---|---|---|
| **D1** | **SMARD.de API** | Live 15-min German market & generation | 0 MB (On-demand API / Fixture) | REST query (`01_forecast.py`) | In-memory / cache |
| **D2** | **ENTSO-E Platform** | Cross-border flows & redispatch | 0 MB (On-demand API) | REST query (API token) | In-memory / cache |
| **D3** | **SimBench Grids** | AC Medium/Low Voltage benchmark grid graphs | Pre-bundled (~90 MB) | `pip install simbench` | Pre-installed wheel |
| **D4** | **FAU elpv-dataset** | Solar cell EL defect images (2,624 PNGs) | ~45 MB | `scripts/bootstrap_data.py` | `data/elpv/` |
| **D5** | **OPSD Weather/Solar**| Historical offline training & validation | ~8 MB (Parquet slice) | `scripts/bootstrap_data.py` | `data/opsd/` |

---

## 4. Production Test Suites & Invariant Verification Matrix

Every run must uphold three invariant tiers:

| Invariant ID | Target Module | Condition / Assertion | Failure Mode Caught |
|---|---|---|---|
| **INV-001** | `01_forecast.py` | $P_{solar} \ge 0.0$ for all records | Sensor noise, corrupted negative generation readings |
| **INV-002** | `01_forecast.py` | $P_{predicted} \ge 0.0$ | Unphysical negative nocturnal forecasts |
| **INV-003** | `01_forecast.py` | Quantile monotonicity: $q_{10} \le q_{50} \le q_{90}$ | Quantile crossing anomalies in gradient boosting |
| **INV-004** | `02_vision.py` | Degradation index $D_{pv} \in [0.0, 1.0]$ | Negative scaling factors, out-of-bounds array slicing |
| **INV-005** | `02_vision.py` | $P_{effective} \le P_{predicted}$ | Defect calculation accidentally increasing generation |
| **INV-006** | `02_vision.py` | $P_{effective} \ge 0.0$ | Over-derating causing negative injected power |
| **INV-007** | `03_grid_physics.py` | $V_{min} \ge 0.85$ p.u. (EN 50160) | Severe bus undervoltage |
| **INV-008** | `03_grid_physics.py` | $V_{max} \le 1.15$ p.u. (EN 50160) | Feeder overvoltage from excess solar reverse power |
| **INV-009** | `04_copilot.py` | SCADA actuation blocked when `operator_approved == False` | Autonomous actuation without human oversight (EU AI Act violation) |
| **INV-010** | `04_copilot.py` | `legal_basis` non-empty in curtailment proposals | Missing regulatory justification (BNetzA Redispatch 2.0 / EnWG §13) |
| **INT-001** | `pipeline.py` | Full pipeline execution < 60s in fixture mode | Runtime performance bottlenecks or infinite retry loops |
| **INT-002** | `libs/contracts/` | Out-of-band values raise `ValidationError` | Type coercion and boundary enforcement failures |

---

## 5. Step-by-Step Antigravity IDE Operational Commands

### 1. Environment Setup
```powershell
# Create & activate Python virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install all dependencies
pip install -r requirements.txt
```

### 2. Run Invariant Verification Suite
```powershell
# Fast local execution (< 5 seconds)
.venv\Scripts\pytest -v
```

### 3. Run End-to-End Pipeline
```powershell
# Offline fixture mode (default)
.venv\Scripts\python pipeline.py --mode fixture --topology simbench-mv-rural --no-copilot

# Live SMARD telemetry
.venv\Scripts\python pipeline.py --mode live --topology simbench-mv-rural --no-copilot

# With Gemini Copilot enabled (requires GEMINI_API_KEY environment variable)
$env:GEMINI_API_KEY = "your-api-key"
.venv\Scripts\python pipeline.py --mode fixture
```

### 4. Bootstrap Open Data (D4 & D5)
```powershell
# Auto-downloads FAU ELPV dataset (~45MB) and OPSD 2020 Parquet slice (~8MB)
.venv\Scripts\python scripts/bootstrap_data.py
```
