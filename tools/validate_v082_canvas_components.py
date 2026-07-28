#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import validate_v082_canvas_components_core as core


if __name__ == "__main__":
    # During contract discovery, record canonical deviations without stopping the
    # full comparison run. Generated candidates remain strict unless explicitly
    # invoked with --diagnostic.
    if len(sys.argv) > 1 and Path(sys.argv[1]).name.startswith("00_V0.8.2_CANVAS") and "--diagnostic" not in sys.argv:
        sys.argv.append("--diagnostic")
    core.main()
