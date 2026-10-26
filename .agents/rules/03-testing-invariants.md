# Testing Invariants — ASG-RAOP

All tests below are **mandatory**. A failing invariant blocks merging to main.

---

## Physical Boundary Invariants (Module 1 — Forecaster)

| ID | Assertion | Rationale |
|---|---|---|
| INV-001 | `P_solar >= 0.0` for all SMARD records | Physical: solar cannot generate negative power |
| INV-002 | `predicted_solar_mw >= 0.0` | Physical: forecast must respect non-negativity |
| INV-003 | `quantile_10_mw <= quantile_50_mw <= quantile_90_mw` | Statistical: quantile ordering |

## Physical Boundary Invariants (Module 2 — Vision)

| ID | Assertion | Rationale |
|---|---|---|
| INV-004 | `D_pv ∈ [0.0, 1.0]` | Degradation scalar is a probability |
| INV-005 | `effective_solar_mw <= predicted_solar_mw` | Degradation can only reduce output |
| INV-006 | `effective_solar_mw >= 0.0` | Physical: cannot extract negative power |

## Physical Boundary Invariants (Module 3 — Grid Physics)

| ID | Assertion | Rationale |
|---|---|---|
| INV-007 | `min_bus_voltage_pu >= 0.85` | EN 50160 lower voltage limit |
| INV-008 | `max_bus_voltage_pu <= 1.15` | EN 50160 upper voltage limit |

## Regulatory Invariants (Module 4 — Copilot)

| ID | Assertion | Rationale |
|---|---|---|
| INV-009 | SCADA write blocked when `operator_approved == False` | EU AI Act / human-in-the-loop |
| INV-010 | `legal_basis` non-empty in all curtailment proposals | BNetzA transparency requirement |

## Integration Invariants

| ID | Assertion | Rationale |
|---|---|---|
| INT-001 | Full pipeline completes in < 60 seconds with fixture data | Performance baseline |
| INT-002 | Pydantic validation raises `ValidationError` for out-of-band values | Contract enforcement |

---

## Enforcement

All invariants are codified as `pytest` test cases in `test_pipeline.py`.
The Antigravity test workflow (`.agents/workflows/test-e2e.md`) runs these
automatically on every relevant file change.

**No code change that causes an invariant to fail may be merged.**
