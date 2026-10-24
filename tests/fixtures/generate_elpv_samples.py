"""
tests/fixtures/generate_elpv_samples.py
=======================================
Pure-Python (standard library only: zlib, struct) generator for 8-bit grayscale PNGs.
Bypasses Windows AppLocker / Application Control policies on third-party C-extension DLLs.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "elpv_samples"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def write_grayscale_png(filename: Path, width: int, height: int, pixels: list[list[int]]) -> None:
    """Writes an 8-bit grayscale PNG using only Python standard library (struct + zlib)."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    # PNG Signature
    sig = b"\x89PNG\r\n\x1a\n"

    # IHDR: width, height, bit_depth=8, color_type=0 (grayscale), comp=0, filter=0, interlace=0
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    ihdr = chunk(b"IHDR", ihdr_data)

    # Scanlines: each row starts with filter byte 0x00
    raw = bytearray()
    for row in pixels:
        raw.append(0)  # filter type 0: None
        raw.extend(row)

    idat = chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    iend = chunk(b"IEND", b"")

    with open(filename, "wb") as f:
        f.write(sig + ihdr + idat + iend)


def main():
    width, height = 300, 300

    # 1. Functional / Pristine Cell: uniform high luminescence ~200, busbars at x=75, 150, 225
    pixels_func = []
    for y in range(height):
        row = []
        for x in range(width):
            val = 200 + ((x * 7 + y * 13) % 15)  # slight grain
            if abs(x - 75) <= 2 or abs(x - 150) <= 2 or abs(x - 225) <= 2:
                val = 230
            row.append(min(255, val))
        pixels_func.append(row)
    write_grayscale_png(OUT_DIR / "functional_cell.png", width, height, pixels_func)

    # 2. Microcrack Cell: dark crack line crossing diagonally
    pixels_crack = []
    for y in range(height):
        row = []
        for x in range(width):
            val = pixels_func[y][x]
            # Diagonal crack trajectory
            target_x = int(y * 0.8 + 20)
            if abs(x - target_x) <= 1 and 50 <= y <= 250:
                val = 30
            row.append(val)
        pixels_crack.append(row)
    write_grayscale_png(OUT_DIR / "microcrack_cell.png", width, height, pixels_crack)

    # 3. Busbar Corrosion: dark corroded patches along busbars
    pixels_corrosion = []
    for y in range(height):
        row = []
        for x in range(width):
            val = pixels_func[y][x]
            for bx in [75, 150, 225]:
                for by in [40, 140, 220]:
                    if abs(x - bx) <= 12 and by <= y <= by + 40:
                        val = 45
            row.append(val)
        pixels_corrosion.append(row)
    write_grayscale_png(OUT_DIR / "busbar_corrosion.png", width, height, pixels_corrosion)

    # 4. Severely Damaged: major dark inactive zones
    pixels_damaged = []
    for y in range(height):
        row = []
        for x in range(width):
            val = pixels_func[y][x]
            if (x < 160 and y < 180) or (x > 180 and y > 200):
                val = 25  # inactive dark crystal area
            row.append(val)
        pixels_damaged.append(row)
    write_grayscale_png(OUT_DIR / "severely_damaged.png", width, height, pixels_damaged)

    print(f"Successfully generated 4 offline ELPV sample fixtures in {OUT_DIR}")


if __name__ == "__main__":
    main()
