# End-to-End Test Workflow — ASG-RAOP
# Antigravity IDE Slash-Command Workflow

## Trigger

Run this workflow manually or automatically on changes to:
- `modules/*.py`
- `libs/contracts/*.py`
- `pipeline.py`

## Steps

### Step 1: Activate Virtual Environment

```powershell
.\.venv\Scripts\Activate.ps1
```

### Step 2: Run Physical Invariant Test Suite

```powershell
pytest test_pipeline.py -v --tb=short
```

Expected output: All 12 tests PASSED.

Any `FAILED` or `ERROR` is a **blocking failure**. Do not proceed.

### Step 3: Run Full Pipeline with Fixture Data

```powershell
python pipeline.py --mode=fixture
```

Expected: JSON summary printed to stdout. No exceptions.

### Step 4: Validate Log Output

Check that `data/logs/incidents.jsonl` contains at least one entry
with `"scada_write_blocked": true` if `redispatch_required` was true.

## Pass Criteria

- [ ] All 12 `test_pipeline.py` tests pass
- [ ] `pipeline.py` exits with code 0
- [ ] `incidents.jsonl` is well-formed JSON Lines
- [ ] No `CRITICAL` log entries in stdout

## Failure Handling

If any step fails:
1. Read the pytest traceback carefully
2. Identify which invariant (INV-xxx or INT-xxx) was violated
3. Fix the root cause in the relevant module
4. Re-run this workflow from Step 1
