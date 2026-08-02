#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import validate_v082_reader_semantics_v3 as base


TABLE_LIKE = re.compile(r"^(?:Extended Data |Supplementary )?Table\b", re.I)
PROVENANCE = "ai-verified-structured-table-transcription-v1"
UPGRADE_ISSUES = {
    "asset kind changed",
    "translated table changed column count",
    "translated table changed row count",
}
PROMOTED_FIGURE_ISSUES = {
    "panel explanation contains no traceable source entity or value",
    "figure explanations are suspiciously templated/repeated",
}


def norm(value: Any) -> str:
    return base.base.norm(value)


def digest(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def allowed_table_upgrade(target: dict[str, Any], source: dict[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if source.get("kind") != "figure" or target.get("kind") != "table":
        return False, errors
    if not (
        TABLE_LIKE.match(norm(source.get("title_en")))
        or TABLE_LIKE.match(norm(source.get("id")).replace("-", " "))
    ):
        errors.append("source asset is not explicitly table-like")
    source_render = norm(target.get("source_render"))
    if PROVENANCE not in source_render:
        errors.append("structured-table provenance marker is missing")
    if "source-image-retained" not in source_render:
        errors.append("source-image-retained provenance flag is missing")
    if norm(target.get("title_en")) != norm(source.get("title_en")):
        errors.append("source table title changed")
    if norm(target.get("caption_en")) != norm(source.get("caption_en")):
        errors.append("source table caption changed")
    if target.get("source_page") != source.get("source_page"):
        errors.append("source page changed")

    target_image = norm(target.get("image_src"))
    source_image = norm(source.get("image_src"))
    if not target_image:
        errors.append("original source table image is not retained")
    elif source_image and digest(target_image) != digest(source_image):
        errors.append("retained table image differs from source evidence")

    table = target.get("table") or {}
    headers = [norm(value) for value in table.get("headers") or []]
    rows = [[norm(value) for value in row] for row in table.get("rows") or []]
    if len(headers) < 2:
        errors.append("structured table has fewer than two headers")
    if not rows:
        errors.append("structured table has no rows")
    if headers and any(len(row) != len(headers) for row in rows):
        errors.append("structured table contains ragged rows")
    if headers and any(not value for value in headers):
        errors.append("structured table contains an empty header")
    if rows and any(all(not value for value in row) for row in rows):
        errors.append("structured table contains an empty row")
    if len({tuple(row) for row in rows}) != len(rows):
        errors.append("structured table contains duplicate rows")
    return not errors, errors


def validate(manifest: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    result = base.validate(manifest, evidence)
    m_assets = {str(item.get("id")): item for item in manifest.get("assets") or []}
    e_assets = {str(item.get("id")): item for item in evidence.get("assets") or []}
    allowed: set[str] = set()
    upgrade_errors: list[dict[str, Any]] = []

    for asset_id, source in e_assets.items():
        target = m_assets.get(asset_id)
        if not target or source.get("kind") == target.get("kind"):
            continue
        passed, issues = allowed_table_upgrade(target, source)
        if passed:
            allowed.add(asset_id)
        elif source.get("kind") == "figure" and target.get("kind") == "table":
            upgrade_errors.append({
                "path": f"assets/{asset_id}",
                "issue": "invalid source-grounded figure-to-table upgrade",
                "detail": issues,
            })

    hard_errors: list[dict[str, Any]] = []
    for item in result.get("errors") or []:
        path = str(item.get("path") or "")
        issue = item.get("issue")
        if issue in UPGRADE_ISSUES and any(
            path.startswith(f"assets/{asset_id}/") for asset_id in allowed
        ):
            continue
        hard_errors.append(item)
    hard_errors.extend(upgrade_errors)

    warnings: list[dict[str, Any]] = []
    for item in result.get("warnings") or []:
        if item.get("issue") in PROMOTED_FIGURE_ISSUES:
            hard_errors.append({
                **item,
                "severity": "error",
                "reason": "panel-specific explanations must be source-traceable and non-templated",
            })
        else:
            warnings.append(item)

    for asset_id in sorted(allowed):
        warnings.append({
            "path": f"assets/{asset_id}",
            "issue": "source table image was upgraded to an AI-transcribed, independently reviewed structured table",
            "severity": "audited-transformation",
        })

    result.update({
        "version": "v082-reader-semantics-4",
        "allowed_structured_table_upgrades": sorted(allowed),
        "promoted_figure_grounding_issues": sorted(PROMOTED_FIGURE_ISSUES),
        "errors": hard_errors,
        "warnings": warnings,
        "passed": not hard_errors,
    })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate source-grounded reader content, audited table recovery and panel-specific figure explanations"
    )
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
