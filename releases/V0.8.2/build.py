#!/usr/bin/env python3
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
CHUNKS = ROOT / "releases/V0.8.2/source/patch_chunks"
PATCH = ROOT / "releases/V0.8.2/source/from_V0.8.1.patch.json.gz.b64"
BASE = ROOT / "published/V0.8.1_CANVAS_Cellular_architecture_and_neighborhood-informed_virtual_spatial_tumor_profiling.html"
TARGET = ROOT / "published/V0.8.2_CANVAS_Cellular_architecture_and_neighborhood-informed_virtual_spatial_tumor_profiling.html"
parts = sorted(CHUNKS.glob("chunk_*.b64"))
if len(parts) != 7:
    raise SystemExit(f"expected 7 patch chunks, found {len(parts)}")
PATCH.parent.mkdir(parents=True, exist_ok=True)
PATCH.write_text("".join(p.read_text("utf-8") for p in parts), "utf-8")
subprocess.run(["python", str(ROOT / "tools/apply_line_patch.py"), str(BASE), str(PATCH), str(TARGET)], check=True)
print(TARGET)
