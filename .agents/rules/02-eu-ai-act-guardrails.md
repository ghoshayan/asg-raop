# EU AI Act Guardrails — ASG-RAOP

Scope: EU AI Act Article 6(3) — Advisory-only ML in energy infrastructure.

---

## Rule EU-01: Advisory-Only Enforcement

No ML model output in this system may autonomously trigger a physical action
(grid switching, SCADA write, asset curtailment) **without explicit human approval**.

The `operator_approved` flag in `CurtailmentProposal` must be `True`
AND `approving_operator_id` must be non-null before any SCADA write proceeds.

Violation of this rule is a **blocking invariant** tested in `test_pipeline.py::test_inv_009`.

## Rule EU-02: Transparency & Confidence Intervals

All ML predictions must carry:
- `model_version` string (e.g. `"LightGBM-v1"`)
- Quantile bounds (`quantile_10_mw`, `quantile_90_mw`) for uncertainty communication
- Training data date range (logged at startup)

This satisfies Article 13 (Transparency) of the EU AI Act.

## Rule EU-03: Model Cards Required

Before any ML model is used in production:
1. A model card must exist at `docs/model_cards/<model_name>.md`
2. Model card must include: architecture, training dataset, validation metrics,
   known failure modes, and update frequency.

## Rule EU-04: Immutable Audit Log

Every AI-generated curtailment proposal must be written to
`data/logs/incidents.jsonl` immediately upon generation, **before** human review.

Log entries are append-only. No log entry may be modified or deleted.

Required fields per entry:
```json
{
  "timestamp": "<ISO-8601 UTC>",
  "module": "04_copilot",
  "model_version": "gemini-2.5-flash",
  "grid_state": {},
  "proposal": {},
  "operator_approved": false,
  "scada_write_blocked": true
}
```

## Rule EU-05: Explainability on Demand

The copilot (Module 4) must include a `legal_basis` field citing the specific
EnWG paragraph for every curtailment proposal. Generic responses without
legal citation are rejected.

## Rule EU-06: No Training on Live Operational Data Without Consent

The LightGBM model may only be retrained on data that has been explicitly
cleared for ML use. Live SCADA operational data must not be used for training
without documented data governance approval.
