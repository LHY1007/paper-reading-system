#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROVENANCE = "ai-verified-structured-table-transcription-v1"


def norm(value: Any) -> str:
    return " ".join(str(value or "").split())


def validate_reviewed_table(asset: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    asset_id = str(asset.get("id") or "")
    if asset.get("kind") != "table":
        errors.append(f"{asset_id}: reviewed table asset is not kind=table")
        return errors
    if PROVENANCE not in norm(asset.get("source_render")):
        errors.append(f"{asset_id}: reviewed table provenance marker is missing")
    if not norm(asset.get("image_src")):
        errors.append(f"{asset_id}: original source table image is not retained")
    table = asset.get("table") or {}
    headers = table.get("headers") or []
    rows = table.get("rows") or []
    if len(headers) < 2:
        errors.append(f"{asset_id}: fewer than two table headers")
    if not rows:
        errors.append(f"{asset_id}: no table rows")
    if headers:
        for row_index, row in enumerate(rows):
            if len(row) != len(headers):
                errors.append(
                    f"{asset_id}: row {row_index} has {len(row)} cells; expected {len(headers)}"
                )
    return errors


def normalize_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate paper-specific table upgrades without rewriting reader content.

    Previous revisions silently replaced the AI-transcribed, independently reviewed
    Andani tables with a hard-coded English-only fallback. That destroyed bilingual
    cells, changed provenance, and made semantic validation disagree with generation.
    The normalizer is now deliberately non-generative: it may validate a reviewed
    upgrade, but it may never invent or overwrite table content.
    """
    paper_key = str((manifest.get("paper") or {}).get("key") or "")
    if paper_key != "andani-2025":
        return manifest

    expected = {
        "extended-data-table-1",
        "extended-data-table-2",
        "extended-data-table-3",
        "extended-data-table-4",
    }
    assets = {str(item.get("id") or ""): item for item in manifest.get("assets") or []}
    missing = sorted(expected - set(assets))
    if missing:
        raise RuntimeError(f"Andani reviewed table assets missing from manifest: {missing}")

    errors: list[str] = []
    for asset_id in sorted(expected):
        errors.extend(validate_reviewed_table(assets[asset_id]))
    if errors:
        raise RuntimeError("Andani reviewed table validation failed: " + "; ".join(errors))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate source-grounded, independently reviewed paper-specific tables"
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.manifest
    manifest = normalize_manifest(json.loads(args.manifest.read_text("utf-8")))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({
        "paper_key": (manifest.get("paper") or {}).get("key"),
        "structured_table_count": sum(
            1 for item in manifest.get("assets") or [] if item.get("kind") == "table"
        ),
        "content_rewritten": False,
        "output": str(output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
