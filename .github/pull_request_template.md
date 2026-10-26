## Summary of Changes
<!-- Provide a clear, concise description of what this PR accomplishes and why. -->

## Motivation & Regulatory Context
<!-- Does this affect Redispatch 2.0 calculations, EU AI Act compliance, or EN 50160 voltage limits? -->

## Invariant Checklist
- [ ] `INV-001 / INV-002`: Solar generation forecasts remain strictly non-negative ($P \ge 0.0$).
- [ ] `INV-003`: Quantile monotonicity holds ($q_{10} \le q_{50} \le q_{90}$).
- [ ] `INV-004 - INV-006`: Vision degradation factor bounded ($D_{pv} \in [0.0, 1.0]$) and $P_{effective} \le P_{forecast}$.
- [ ] `INV-007 / INV-008`: EN 50160 voltage band checks are respected.
- [ ] `INV-009`: SCADA write barrier remains unconditionally locked (`scada_write_blocked=True`) without human operator signature.
- [ ] `INV-010`: All curtailment proposals contain non-empty statutory citation (e.g. `EnWG §13 Abs. 1`).

## Presubmit Verification
- [ ] `python scripts/presubmit.py` passes with exit code 0.
- [ ] Unit tests pass across Python matrix in CI.
