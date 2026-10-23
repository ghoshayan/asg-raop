"""
modules/02_vision.py — Computer Vision Asset Inspector
=======================================================
Module 2 of the ASG-RAOP pipeline.

Responsibilities:
  1. Load a solar cell Electroluminescence (EL) image from disk.
  2. Run defect inference via ONNX Runtime (stub session in dev mode).
  3. Compute the degradation scalar D_pv ∈ [0.0, 1.0].
  4. Adjust available generation: P_effective = P_forecast × (1 − D_pv).
  5. Return a validated DegradationOutput Pydantic model.

Physical invariants enforced:
  INV-004: D_pv ∈ [0.0, 1.0]
  INV-005: effective_solar_mw <= predicted_solar_mw
  INV-006: effective_solar_mw >= 0.0

Fallback strategy:
  If ONNX model is unavailable or inference fails → D_pv = 0.0 (healthy asset).
  This is conservative: we assume no degradation rather than blocking the pipeline.

Public API:
    run(predicted_solar_mw: float,
        asset_id: str,
        image_path: Optional[Path],
        onnx_model_path: Optional[Path]) -> dict
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ONNX Runtime — optional, graceful fallback to stub if unavailable
try:
    import onnxruntime as ort  # type: ignore

    _ORT_AVAILABLE = True
except ImportError:
    _ORT_AVAILABLE = False
    logger.warning("onnxruntime not installed — using stub defect inference.")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Input resolution expected by the ONNX model (H × W × C)
MODEL_INPUT_H = 256
MODEL_INPUT_W = 256
MODEL_INPUT_C = 1  # Grayscale EL images

# Stub defect probability: simulates a mildly degraded asset (D_pv = 0.20)
_STUB_DEFECT_MEAN = 0.20
_STUB_CONFIDENCE = 0.85


# ---------------------------------------------------------------------------
# Image loading & preprocessing
# ---------------------------------------------------------------------------


def _load_png_pure_python(image_path: Path) -> np.ndarray:
    """Pure-Python standard library reader for 8-bit grayscale PNGs (immune to AppLocker DLL blocks)."""
    import struct
    import zlib

    with open(image_path, "rb") as f:
        data = f.read()

    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a valid PNG file: {image_path}")

    offset = 8
    width, height = 0, 0
    idat_parts = []
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height = struct.unpack(">II", chunk_data[:8])
        elif chunk_type == b"IDAT":
            idat_parts.append(chunk_data)
        elif chunk_type == b"IEND":
            break

    decompressed = zlib.decompress(b"".join(idat_parts))
    stride = 1 + width
    rows = []
    prev_row = bytearray(width)
    for r in range(height):
        filter_byte = decompressed[r * stride]
        row_raw = bytearray(decompressed[r * stride + 1 : (r + 1) * stride])
        if filter_byte == 1:  # Sub
            for c in range(1, width):
                row_raw[c] = (row_raw[c] + row_raw[c - 1]) & 0xFF
        elif filter_byte == 2:  # Up
            for c in range(width):
                row_raw[c] = (row_raw[c] + prev_row[c]) & 0xFF
        elif filter_byte == 3:  # Average
            for c in range(width):
                left = row_raw[c - 1] if c > 0 else 0
                row_raw[c] = (row_raw[c] + ((left + prev_row[c]) // 2)) & 0xFF
        elif filter_byte == 4:  # Paeth
            for c in range(width):
                a = row_raw[c - 1] if c > 0 else 0
                b = prev_row[c]
                c_diag = prev_row[c - 1] if c > 0 else 0
                p = a + b - c_diag
                pa = abs(p - a)
                pb = abs(p - b)
                pc = abs(p - c_diag)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c_diag)
                row_raw[c] = (row_raw[c] + pr) & 0xFF
        prev_row = row_raw
        rows.append(list(row_raw))

    arr = np.array(rows, dtype=np.float32) / 255.0
    # Downsample / resize to MODEL_INPUT_H, MODEL_INPUT_W
    if arr.shape != (MODEL_INPUT_H, MODEL_INPUT_W):
        y_indices = np.linspace(0, height - 1, MODEL_INPUT_H).astype(int)
        x_indices = np.linspace(0, width - 1, MODEL_INPUT_W).astype(int)
        arr = arr[np.ix_(y_indices, x_indices)]
    return arr[np.newaxis, np.newaxis, :, :]


def _load_and_preprocess(image_path: Path) -> np.ndarray:
    """
    Load an EL image from disk, convert to float32 grayscale, resize,
    and add batch + channel dims → shape [1, 1, H, W].
    Attempts PIL first; seamlessly falls back to pure-Python decoder.
    """
    try:
        from PIL import Image  # type: ignore

        img = Image.open(image_path).convert("L")  # L = grayscale
        img = img.resize((MODEL_INPUT_W, MODEL_INPUT_H))
        arr = np.array(img, dtype=np.float32) / 255.0  # normalise to [0, 1]
        return arr[np.newaxis, np.newaxis, :, :]
    except Exception as exc:
        logger.debug("PIL image loading unavailable (%s) — using pure Python decoder.", exc)
        return _load_png_pure_python(image_path)


# ---------------------------------------------------------------------------
# ONNX inference (real)
# ---------------------------------------------------------------------------


def _run_onnx_inference(onnx_model_path: Path, image_array: np.ndarray) -> np.ndarray:
    """
    Run a segmentation ONNX model and return the pixel-wise defect
    probability mask of shape [H, W].
    """
    if not _ORT_AVAILABLE:
        raise RuntimeError("onnxruntime is not installed.")

    sess = ort.InferenceSession(
        str(onnx_model_path), providers=["CPUExecutionProvider"]
    )
    input_name = sess.get_inputs()[0].name
    output = sess.run(None, {input_name: image_array})
    # Assume model output is [1, 1, H, W] sigmoid probabilities
    mask = output[0].squeeze()  # [H, W]
    return mask.astype(np.float32)


# ---------------------------------------------------------------------------
# Stub inference (dev mode — no real ONNX model required)
# ---------------------------------------------------------------------------


def _run_stub_inference(image_array: Optional[np.ndarray] = None) -> np.ndarray:
    """
    Return a defect probability mask for reproducible offline development.
    If image_array is provided, computes an empirical defect mask from dark inactive pixels.
    Otherwise, simulates a mildly degraded asset: D_pv ≈ 0.20.
    """
    if image_array is not None:
        # In electroluminescence, dark pixels (< 0.60 intensity) indicate inactive/cracked crystal regions
        squeezed = image_array.squeeze()
        mask = np.clip((0.60 - squeezed) / 0.60, 0.0, 1.0)
        return mask.astype(np.float32)

    logger.info(
        "Using stub ONNX session (D_pv=%.2f). "
        "Replace with a real .onnx model for production.",
        _STUB_DEFECT_MEAN,
    )
    rng = np.random.default_rng(seed=42)
    mask = rng.uniform(
        low=max(0.0, _STUB_DEFECT_MEAN - 0.05),
        high=min(1.0, _STUB_DEFECT_MEAN + 0.05),
        size=(MODEL_INPUT_H, MODEL_INPUT_W),
    ).astype(np.float32)
    return mask


# ---------------------------------------------------------------------------
# Degradation scalar computation
# ---------------------------------------------------------------------------


def _compute_degradation_scalar(mask: np.ndarray) -> tuple[float, float]:
    """
    D_pv = mean(defect_mask_probabilities)  ∈ [0.0, 1.0]
    Confidence = 1 - std(mask)  (lower variance → higher confidence)
    """
    d_pv = float(np.mean(mask))
    d_pv = float(np.clip(d_pv, 0.0, 1.0))  # INV-004 hard clamp
    confidence = float(np.clip(1.0 - np.std(mask), 0.0, 1.0))
    return d_pv, confidence


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run(
    predicted_solar_mw: float,
    asset_id: str = "PV-ASSET-001",
    image_path: Optional[Path] = None,
    onnx_model_path: Optional[Path] = None,
) -> dict:
    """
    Module 2 entry point.

    Args:
        predicted_solar_mw: Upstream forecast value from Module 1.
        asset_id:           Identifier for the PV asset.
        image_path:         Path to the EL image (optional; uses stub if None).
        onnx_model_path:    Path to the ONNX segmentation model (optional).

    Returns:
        DegradationOutput as a dict (validated Pydantic model).
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from libs.contracts.degradation import DegradationOutput

    # Enforce non-negativity on upstream input
    predicted_solar_mw = max(0.0, predicted_solar_mw)

    # --- Inference ---
    model_version = "ONNX-stub-v0"
    mask: np.ndarray

    use_real_model = (
        _ORT_AVAILABLE
        and onnx_model_path is not None
        and onnx_model_path.exists()
        and image_path is not None
        and image_path.exists()
    )

    if use_real_model:
        try:
            image_array = _load_and_preprocess(image_path)  # type: ignore[arg-type]
            mask = _run_onnx_inference(onnx_model_path, image_array)  # type: ignore[arg-type]
            model_version = f"ONNX-{onnx_model_path.stem}"
            logger.info("Real ONNX inference completed for asset %s.", asset_id)
        except Exception as exc:
            logger.warning(
                "ONNX inference failed (%s). Falling back to stub with D_pv=0.0.",
                exc,
            )
            mask = np.zeros((MODEL_INPUT_H, MODEL_INPUT_W), dtype=np.float32)
    else:
        if image_path is not None and Path(image_path).exists():
            image_array = _load_and_preprocess(Path(image_path))
            mask = _run_stub_inference(image_array=image_array)
            model_version = "ELPV-empirical-v1"
        else:
            mask = _run_stub_inference()

    # --- Compute degradation ---
    d_pv, confidence = _compute_degradation_scalar(mask)
    p_effective = max(0.0, predicted_solar_mw * (1.0 - d_pv))  # INV-006

    # --- Build & validate via Pydantic ---
    output = DegradationOutput(
        asset_id=asset_id,
        degradation_scalar=d_pv,
        defect_mask_path=None,  # mask not persisted to disk in stub mode
        effective_solar_mw=p_effective,
        predicted_solar_mw=predicted_solar_mw,
        confidence=confidence,
        model_version=model_version,
    )

    logger.info(
        "Module 2 complete: D_pv=%.4f  P_effective=%.2f MW  confidence=%.3f",
        output.degradation_scalar,
        output.effective_solar_mw,
        output.confidence,
    )
    return output.model_dump()
