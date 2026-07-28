#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from bs4 import BeautifulSoup
import validate_v082_canvas_components_core as core


_original_validate = core.validate


def validate(path: Path) -> dict:
    report = _original_validate(path)
    soup = BeautifulSoup(path.read_text("utf-8"), "html.parser")
    errors = report["errors"]
    for index, citation in enumerate(soup.select("#bilingual-pane .citation"), 1):
        refs = citation.get("data-refs")
        if not refs:
            errors.append(f"citation {index} missing canonical data-refs")
        elif any(not part.strip().isdigit() for part in refs.split(",")):
            errors.append(f"citation {index} has invalid data-refs {refs!r}")
        if citation.get("role") != "button" or citation.get("tabindex") != "0":
            errors.append(f"citation {index} accessibility mismatch")
        if citation.has_attr("data-ref"):
            errors.append(f"citation {index} uses obsolete data-ref")
    report["citation_count"] = len(soup.select("#bilingual-pane .citation"))
    report["passed"] = not errors
    return report


core.validate = validate


if __name__ == "__main__":
    # During contract discovery, record original 00 deviations without stopping the
    # comparison run. The normalized master and generated candidates remain strict.
    if len(sys.argv) > 1 and Path(sys.argv[1]).name.startswith("00_V0.8.2_CANVAS") and "--diagnostic" not in sys.argv:
        sys.argv.append("--diagnostic")
    core.main()
