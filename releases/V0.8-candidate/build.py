#!/usr/bin/env python3
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "published/V0.7.8_CANVAS_Cellular_architecture_and_neighborhood-informed_virtual_spatial_tumor_profiling.html"
TARGET = ROOT / "published/V0.8_CANVAS_Cellular_architecture_and_neighborhood-informed_virtual_spatial_tumor_profiling.html"
SOURCE = Path(__file__).resolve().parent / "source"
EXPECTED_SHA256 = "c02aad24689eefaed372decb3068f339a83d5c15fdf8b45f259c019418ceece2"

base = BASE.read_text("utf-8")
css = (SOURCE / "v080.css").read_text("utf-8")
js = (SOURCE / "v080.js").read_text("utf-8")
manifest = (SOURCE / "review_manifest.json").read_text("utf-8").strip()

if '<title>CANVAS – V0.7.8</title>' not in base:
    raise SystemExit("V0.7.8 title marker missing")
if '<meta content="0.7.8" name="paper-reader-version"/>' not in base:
    raise SystemExit("V0.7.8 version marker missing")
if base.count('</head>') != 1:
    raise SystemExit("unexpected head boundary")

candidate = base.replace('<title>CANVAS – V0.7.8</title>', '<title>CANVAS – V0.8 Candidate</title>', 1)
candidate = candidate.replace('<meta content="0.7.8" name="paper-reader-version"/>', '<meta content="0.8.0-candidate" name="paper-reader-version"/>', 1)
insert = (
    '<style id="canvas-v080-style">' + css + '</style>\n'
    '<script type="application/json" id="v080ReviewManifest">' + manifest + '</script>\n'
    '<script id="canvas-v080-script">' + js + '</script>\n'
)
candidate = candidate.replace('</head>', insert + '</head>', 1)

base_body = base[base.index('<body'):]
candidate_body = candidate[candidate.index('<body'):]
if base_body != candidate_body:
    raise SystemExit("body/content changed during V0.8 build")

TARGET.write_text(candidate, "utf-8")
digest = hashlib.sha256(TARGET.read_bytes()).hexdigest()
if digest != EXPECTED_SHA256:
    raise SystemExit(f"SHA256 mismatch: {digest} != {EXPECTED_SHA256}")
print(f"built {TARGET} ({TARGET.stat().st_size:,} bytes), SHA256={digest}")
