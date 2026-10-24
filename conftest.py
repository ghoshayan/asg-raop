"""
conftest.py — Root pytest configuration for ASG-RAOP.

Adds the project root to sys.path so that `libs` and `modules` are
importable without installation, and pre-generates the SMARD fixture
before any tests are collected.
"""

import json
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure project root is on the path for all test imports
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "smard_30d.json"


def _generate_fixture() -> None:
    """Generate synthetic 30-day SMARD fixture if it doesn't exist."""
    if FIXTURE_PATH.exists():
        return

    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)

    INTERVAL_MIN = 15
    DAYS = 30
    STEPS = (DAYS * 24 * 60) // INTERVAL_MIN
    PEAK_MW = 35_000.0

    random.seed(42)
    start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    series = []

    for i in range(STEPS):
        ts = start + timedelta(minutes=i * INTERVAL_MIN)
        hour = ts.hour + ts.minute / 60.0
        doy = ts.timetuple().tm_yday
        seasonal = 0.7 + 0.3 * math.cos(2 * math.pi * (doy - 172) / 365.0)
        solar_fraction = math.exp(-0.5 * ((hour - 12.5) / 3.0) ** 2)
        base = PEAK_MW * seasonal * solar_fraction
        noise = base * random.gauss(0, 0.05)
        cloud = -base * random.uniform(0.3, 0.8) if random.random() < 0.15 else 0.0
        value = max(0.0, base + noise + cloud)
        ts_ms = int(ts.timestamp() * 1000)
        series.append([ts_ms, round(value, 2)])

    with open(FIXTURE_PATH, "w") as f:
        json.dump({"series": series}, f)

    print(f"conftest: generated {STEPS} SMARD records -> {FIXTURE_PATH}")


# Generate at collection time (before any test runs)
_generate_fixture()
