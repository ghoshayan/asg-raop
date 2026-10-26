"""
scripts/bootstrap_data.py — Automated Data Sourcing for ASG-RAOP
================================================================
Fetches and caches open-source datasets D4 and D5 for local development:
  - D4: FAU elpv-dataset (~45 MB zip, 2,624 solar cell EL images)
  - D5: Open Power System Data (OPSD) German weather & solar baseline 2020 (~8 MB parquet)
  - Provisions fast offline test fixtures in tests/fixtures/elpv_samples/

Usage:
  python scripts/bootstrap_data.py               # Fetch both D4 and D5
  python scripts/bootstrap_data.py --elpv-only   # Fetch only D4 (ELPV images)
  python scripts/bootstrap_data.py --opsd-only   # Fetch only D5 (OPSD Parquet)
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import shutil
import zipfile
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bootstrap_data")

# Resolve paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
ELPV_DIR = DATA_DIR / "elpv"
OPSD_DIR = DATA_DIR / "opsd"
FIXTURES_ELPV_DIR = PROJECT_ROOT / "tests" / "fixtures" / "elpv_samples"


def setup_directories() -> None:
    """Ensure data and fixture directories exist."""
    ELPV_DIR.mkdir(parents=True, exist_ok=True)
    OPSD_DIR.mkdir(parents=True, exist_ok=True)
    FIXTURES_ELPV_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Directory scaffold verified at %s", DATA_DIR)


def fetch_d4_elpv(force: bool = False) -> None:
    """
    Auto-downloads and unpacks the FAU elpv-dataset (~45 MB).
    Source: Friedrich-Alexander-Universität Erlangen-Nürnberg (ZAE Bayern).
    """
    elpv_marker = ELPV_DIR / "labels.csv"
    if elpv_marker.exists() and not force:
        logger.info("[D4 - elpv] Dataset already cached at %s", ELPV_DIR)
        _sync_sample_fixtures()
        return

    logger.info("[D4 - elpv] Downloading FAU elpv-dataset from GitHub...")
    zip_url = "https://github.com/zae-bayern/elpv-dataset/archive/refs/heads/master.zip"
    resp = requests.get(zip_url, timeout=60)
    resp.raise_for_status()

    logger.info("[D4 - elpv] Extracting images and labels...")
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        for member in z.namelist():
            if "images/" in member or member.endswith("labels.csv"):
                filename = os.path.basename(member)
                if not filename:
                    continue
                target_path = (
                    ELPV_DIR / ("images" if "images/" in member else "") / filename
                )
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with open(target_path, "wb") as f:
                    f.write(z.read(member))

    logger.info("[D4 - elpv] Extracted successfully to %s", ELPV_DIR)
    _sync_sample_fixtures()


def _sync_sample_fixtures() -> None:
    """Copy 4 representative sample images into tests/fixtures/elpv_samples/ if available."""
    images_dir = ELPV_DIR / "images"
    if not images_dir.exists():
        return

    # Check labels.csv to find diverse samples: 0.0 (healthy), 0.33, 0.66, 1.0 (dead)
    labels_path = ELPV_DIR / "labels.csv"
    if labels_path.exists():
        try:
            df_labels = pd.read_csv(
                labels_path, sep=r"\s+", header=None, names=["rel_path", "score", "type"]
            )
            # Find representative files
            for target_score, name in [
                (0.0, "functional_cell.png"),
                (0.33, "microcrack_cell.png"),
                (0.66, "busbar_corrosion.png"),
                (1.0, "severely_damaged.png"),
            ]:
                matches = df_labels[df_labels["score"] == target_score]
                if not matches.empty:
                    src_name = Path(matches.iloc[0]["rel_path"]).name
                    src_file = images_dir / src_name
                    if src_file.exists():
                        shutil.copyfile(src_file, FIXTURES_ELPV_DIR / name)
            logger.info("[Fixtures] Synced representative ELPV samples to %s", FIXTURES_ELPV_DIR)
        except Exception as exc:
            logger.warning("[Fixtures] Could not parse labels for sample sync: %s", exc)


def fetch_d5_opsd_slice(force: bool = False) -> None:
    """
    Downloads a lightweight, pre-filtered German weather & solar baseline slice (~8 MB)
    instead of the full 1.5 GB multi-country OPSD dump.
    """
    opsd_file = OPSD_DIR / "germany_weather_solar_2020.parquet"
    if opsd_file.exists() and not force:
        logger.info("[D5 - OPSD] German baseline slice already cached at %s", opsd_file)
        return

    logger.info("[D5 - OPSD] Fetching German solar and weather baseline from OPSD...")
    opsd_url = (
        "https://data.open-power-system-data.org/time_series/"
        "2020-10-06/time_series_60min_singleindex.csv"
    )

    columns_to_keep = [
        "utc_timestamp",
        "DE_solar_generation_actual",
        "DE_solar_capacity",
        "DE_solar_profile",
        "DE_wind_generation_actual",
        "DE_wind_capacity",
        "DE_load_actual_entsoe_transparency",
    ]

    try:
        chunks = []
        logger.info("[D5 - OPSD] Streaming & filtering German bidding zone columns...")
        for chunk in pd.read_csv(opsd_url, usecols=columns_to_keep, chunksize=5000):
            chunk["utc_timestamp"] = pd.to_datetime(chunk["utc_timestamp"])
            chunk_2020 = chunk[chunk["utc_timestamp"].dt.year == 2020]
            if not chunk_2020.empty:
                chunks.append(chunk_2020)

        if not chunks:
            raise RuntimeError("No records matched year 2020 in OPSD stream.")

        df_de = pd.concat(chunks, ignore_index=True)
        df_de.to_parquet(opsd_file, compression="snappy", index=False)
        logger.info(
            "[D5 - OPSD] Saved optimized slice (%d rows) to %s (snappy compressed)",
            len(df_de),
            opsd_file,
        )
    except Exception as exc:
        logger.error("[D5 - OPSD] Failed to fetch OPSD slice: %s", exc)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="ASG-RAOP Data Bootstrapper")
    parser.add_argument("--elpv-only", action="store_true", help="Fetch only D4 ELPV dataset")
    parser.add_argument("--opsd-only", action="store_true", help="Fetch only D5 OPSD slice")
    parser.add_argument("--force", action="store_true", help="Force re-download even if cached")
    args = parser.parse_args()

    setup_directories()

    if args.elpv_only:
        fetch_d4_elpv(force=args.force)
    elif args.opsd_only:
        fetch_d5_opsd_slice(force=args.force)
    else:
        fetch_d4_elpv(force=args.force)
        fetch_d5_opsd_slice(force=args.force)

    logger.info("Bootstrap complete. All data dependencies ready for development.")


if __name__ == "__main__":
    main()
