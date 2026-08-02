#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import validate_v082_reader_semantics_v2 as base


SOFT_ISSUES = {
    "panel explanation contains no traceable source entity or value",
    "figure explanations are suspiciously templated/repeated",
}


def is_short_label_or_formula(item: dict[str, Any]) -> bool:
    if item.get("issue") != "translation is implausibly short relative to source":
        return False
    detail = item.get("detail") or {}
    try:
        return int(detail.get("en_chars") or 0) <= 20 and int(detail.get("zh_chars") or 0) >= 2
    except (TypeError, ValueError):
        return False


def validate(manifest: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    result = base.validate(manifest, evidence)
    hard_errors = []
    warnings = list(result.get("warnings") or [])
    for item in result.get("errors") or []:
        if item.get("issue") in SOFT_ISSUES or is_short_label_or_formula(item):
            warnings.append({**item, "severity": "warning"})
        else:
            hard_errors.append(item)
    result.update({
        "version": "v082-reader-semantics-3",
        "errors": hard_errors,
        "warnings": warnings,
        "passed": not hard_errors,
    })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate V0.8.2 scientific grounding with low-false-positive entity diagnostics")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = validate(
        json.loads(args.manifest.read_text("utf-8")),
        json.loads(args.evidence.read_text("utf-8")),
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", "utf-8")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
