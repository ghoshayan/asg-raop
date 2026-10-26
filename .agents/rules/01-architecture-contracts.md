# Architecture Contracts — ASG-RAOP

These rules are enforced by the Antigravity IDE agent for every code change
in the `energy_lab/` workspace.

---

## Rule AC-01: Single-Responsibility Modules

Each file under `modules/` must expose **exactly one** public entry point:

```python
def run(**kwargs) -> dict:
    ...
```

No module may import another module directly. All inter-module data flow
passes through the integration layer (`pipeline.py`).

## Rule AC-02: Pydantic-First Data Contracts

All data that crosses a module boundary **must** be validated by a Pydantic v2
model from `libs/contracts/` before use. Raw dictionaries are only permitted
inside the module that produced them.

Acceptable pattern:
```python
from libs.contracts.telemetry import ForecastOutput
output = ForecastOutput(**raw_dict)     # validates at boundary
```

Forbidden pattern:
```python
# Do NOT pass unvalidated dicts across module boundaries
downstream_module.run(data=raw_dict)
```

## Rule AC-03: Physical Non-Negativity

All solar generation values must satisfy `P >= 0.0`. Apply `.clip(lower=0.0)`
immediately after every SMARD API read and every forecast computation.

## Rule AC-04: No Circular Imports

Import graph must be a DAG:
```
pipeline.py → modules/* → libs/contracts/* → (stdlib / third-party only)
```

## Rule AC-05: Secrets Management

- API keys (Gemini, SMARD if required) must be read from environment variables only.
- No secrets in source code, no secrets in git history.
- Use `os.environ.get("GEMINI_API_KEY")` pattern.

## Rule AC-06: Structured Logging

All modules must use Python's `logging` stdlib (not `print`). Log format:

```python
import logging
logger = logging.getLogger(__name__)
logger.info("Module 1 forecast complete", extra={"predicted_mw": value})
```
