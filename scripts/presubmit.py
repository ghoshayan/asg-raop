#!/usr/bin/env python3
"""
scripts/presubmit.py — Google-Style Pre-Push / Pre-Merge Presubmit Check
========================================================================
Runs local health checks before allowing code to be pushed to GitHub:
  1. Secret & credential leak scan across code files
  2. Fixture asset verification (ELPV sample images & SMARD 30-day baseline)
  3. Invariant test matrix (21 physical, mathematical, and regulatory invariants)
  4. End-to-end pipeline smoke test

Exit codes:
  0: All presubmit checks passed. Safe to push.
  1: One or more checks failed. Push blocked.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Forbidden patterns that must never be committed to git
_SECRET_PATTERNS = [
    (re.compile(r"AIza[0-9A-Za-z-_]{35}"), "Google API Key"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key"),
    (re.compile(r"ghp_[0-9A-Za-z]{36}"), "GitHub Personal Access Token"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "Private Key Block"),
]

# Required fixture files that must exist for hermetic testing
_REQUIRED_FIXTURES = [
    PROJECT_ROOT / "tests" / "fixtures" / "smard_30d.json",
    PROJECT_ROOT / "tests" / "fixtures" / "elpv_samples" / "functional_cell.png",
    PROJECT_ROOT / "tests" / "fixtures" / "elpv_samples" / "microcrack_cell.png",
    PROJECT_ROOT / "tests" / "fixtures" / "elpv_samples" / "busbar_corrosion.png",
    PROJECT_ROOT / "tests" / "fixtures" / "elpv_samples" / "severely_damaged.png",
]


def check_secrets() -> bool:
    """Scan tracked Python and configuration files for exposed secrets."""
    print(" [1/4] Running Secret Leak Scan...")
    scanned_files = 0
    violations = []

    for ext in ("*.py", "*.json", "*.toml", "*.md", "*.yml", "*.yaml"):
        for filepath in PROJECT_ROOT.rglob(ext):
            # Skip virtualenvs, git dir, logs, and caches
            rel = filepath.relative_to(PROJECT_ROOT)
            parts = rel.parts
            if any(p in parts for p in (".venv", ".git", ".pytest_cache", "__pycache__", "data")):
                continue

            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
                scanned_files += 1
                for pattern, secret_type in _SECRET_PATTERNS:
                    if pattern.search(content):
                        violations.append((rel, secret_type))
            except Exception as e:
                print(f"       Warning: could not scan {rel}: {e}")

    if violations:
        print(f"   FAILED: Potential secrets detected in {len(violations)} locations:")
        for file_rel, s_type in violations:
            print(f"     - {file_rel}: {s_type}")
        return False

    print(f"   PASSED: {scanned_files} files scanned, 0 secrets detected.")
    return True


def check_fixtures() -> bool:
    """Ensure all hermetic offline fixtures are present."""
    print(" [2/4] Verifying Hermetic Test Fixtures...")
    missing = [f.relative_to(PROJECT_ROOT) for f in _REQUIRED_FIXTURES if not f.exists()]

    if missing:
        print(f"   FAILED: Missing {len(missing)} required test fixtures:")
        for m in missing:
            print(f"     - {m}")
        print("   Run 'python tests/fixtures/generate_elpv_samples.py' to generate sample fixtures.")
        return False

    print(f"   PASSED: All {len(_REQUIRED_FIXTURES)} offline test fixtures verified on disk.")
    return True


def check_unit_tests() -> bool:
    """Run full 21-invariant pytest suite."""
    print(" [3/4] Running 21-Invariant Pytest Matrix...")
    cmd = [sys.executable, "-m", "pytest", "test_pipeline.py", "-q", "--tb=short"]
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    if result.returncode != 0:
        print("   FAILED: Invariant test suite failed.")
        return False

    print("   PASSED: All 21 physical, mathematical, and regulatory invariants passed.")
    return True


def check_pipeline_smoke() -> bool:
    """Run end-to-end pipeline smoke test in offline mode."""
    print(" [4/4] Running End-to-End Pipeline Smoke Test...")
    cmd = [
        sys.executable,
        "pipeline.py",
        "--mode", "fixture",
        "--topology", "example-mv",
        "--no-copilot",
        "--no-n1",
        "--image-path", "tests/fixtures/elpv_samples/microcrack_cell.png",
    ]
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)

    if result.returncode != 0:
        print("   FAILED: Pipeline smoke test failed with stderr:")
        print(result.stderr[-500:])
        return False

    print("   PASSED: End-to-end pipeline executed successfully in offline mode.")
    return True


def main() -> int:
    print("=" * 65)
    print(" ASG-RAOP Google-SWE Presubmit Gate")
    print("=" * 65)

    checks = [
        check_secrets,
        check_fixtures,
        check_unit_tests,
        check_pipeline_smoke,
    ]

    all_passed = True
    for check in checks:
        if not check():
            all_passed = False
            break

    print("=" * 65)
    if all_passed:
        print(" ALL PRESUBMIT CHECKS PASSED. Ready for git push.")
        print("=" * 65)
        return 0
    else:
        print(" PRESUBMIT GATE FAILED. Fix issues above before pushing.")
        print("=" * 65)
        return 1


if __name__ == "__main__":
    sys.exit(main())
