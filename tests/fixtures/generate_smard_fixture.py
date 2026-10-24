"""
tests/fixtures/generate_smard_fixture.py
Generates a synthetic 30-day SMARD fixture file for offline testing.
Run once: python tests/fixtures/generate_smard_fixture.py
"""

import json
import math
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

INTERVAL_MIN = 15
DAYS = 30
STEPS = (DAYS * 24 * 60) // INTERVAL_MIN
PEAK_MW = 35_000.0   # Germany-wide solar peak ~35 GW in summer

random.seed(42)

start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
series = []

for i in range(STEPS):
    ts = start + timedelta(minutes=i * INTERVAL_MIN)
    hour = ts.hour + ts.minute / 60.0
    doy = ts.timetuple().tm_yday

    # Solar irradiance model: Gaussian bell around solar noon (hour 12.5)
    # plus seasonal factor
    seasonal = 0.7 + 0.3 * math.cos(2 * math.pi * (doy - 172) / 365.0)  # peak at summer solstice
    solar_fraction = math.exp(-0.5 * ((hour - 12.5) / 3.0) ** 2)
    base = PEAK_MW * seasonal * solar_fraction

    # Add noise + cloud cover events
    noise = base * random.gauss(0, 0.05)
    cloud = 0.0
    if random.random() < 0.15:  # 15 % chance of cloud cover
        cloud = -base * random.uniform(0.3, 0.8)

    value = max(0.0, base + noise + cloud)

    ts_ms = int(ts.timestamp() * 1000)
    series.append([ts_ms, round(value, 2)])

output = {"series": series}
out_path = Path(__file__).parent / "smard_30d.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w") as f:
    json.dump(output, f)

print(f"Generated {STEPS} records -> {out_path}")
