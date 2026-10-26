# Contributing to ASG-RAOP

Thank you for your interest in contributing to the **Autonomous Smart Grid & Renewable Asset Orchestration Platform (ASG-RAOP)**!

We welcome contributions from energy data scientists, electrical power engineers, and software architects. This project follows rigorous Google-grade software engineering practices and European regulatory standards (BNetzA Redispatch 2.0, EnWG, EU AI Act).

---

## 1. Development Setup

### Prerequisites
- Python 3.11 or 3.12
- Git

### Initializing the Workspace
```powershell
# Clone the repository
git clone https://github.com/ghoshayan/asg-raop.git
cd asg-raop

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows
# or: source .venv/bin/activate # Linux/macOS

# Install dependencies
pip install -r requirements.txt
```

---

## 2. Invariant & Quality Gate (Presubmit)

Before submitting any code, your changes must pass the presubmit check:
```powershell
python scripts/presubmit.py
```

The presubmit gate verifies:
1. **Secret & Key Hygiene**: Scans files for exposed tokens or private keys.
2. **Hermetic Test Fixtures**: Confirms sample ELPV cell images and SMARD baseline data exist on disk.
3. **21-Invariant Test Matrix**: Executes full pytest suite verifying physical limits, schema validations, and legal gatekeepers.
4. **End-to-End Pipeline Smoke Test**: Verifies complete execution in offline mode.

---

## 3. Commit Discipline & Conventional Commits

We follow Google's Change List (CL) discipline and the **Conventional Commits** specification:

```
<type>(<scope>): <short summary in imperative mood, max 50 chars>

<Detailed explanation of the change, motivation, and trade-offs. Keep lines
under 72 characters where possible.>

Tested:
<Exact test commands run, e.g. python scripts/presubmit.py>
```

### Commit Types
- `feat`: A new user-facing capability or module
- `fix`: A bug fix (e.g. correcting a data ingestion path or calculation)
- `test`: Adding or refactoring invariant tests
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `docs`: Documentation updates
- `ci`: Changes to CI configuration or presubmit scripts
- `chore`: Routine maintenance, dependencies, or repository hygiene

---

## 4. Regulatory & Architectural Non-Negotiables

Any contribution touching the orchestration layer must adhere to two architectural invariants:

1. **EU AI Act Human-in-the-Loop Gatekeeper (`INV-009`)**:
   Under no circumstances may the copilot directly execute SCADA grid actuations. The property `scada_write_blocked` must remain `True` unless explicitly signed off by a human grid operator with valid credentials (`operator_approved=True` and non-empty `approving_operator_id`).
2. **Legal Basis Transparency (`INV-010`)**:
   Every curtailment proposal must cite the exact legal statutory authority (e.g., `EnWG §13 Abs. 1` or `EnWG §13a`). Empty or vague citations will be rejected by Pydantic contracts.
