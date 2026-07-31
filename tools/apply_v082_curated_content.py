#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text("utf-8"))


def load_curated(path: Path) -> dict[str, Any]:
    if path.is_file():
        return load(path)
    if not path.is_dir():
        raise SystemExit(f"curated content path does not exist: {path}")
    files = sorted(path.glob("*.json"))
    if not files:
        raise SystemExit(f"curated content directory contains no JSON files: {path}")
    merged: dict[str, Any] = {"paper_key": "", "terms": [], "studies": {}}
    for file in files:
        part = load(file)
        part_key = str(part.get("paper_key") or "")
        if merged["paper_key"] and part_key != merged["paper_key"]:
            raise SystemExit(
                f"curated paper key mismatch in {file}: {part_key!r} != {merged['paper_key']!r}"
            )
        if part_key:
            merged["paper_key"] = part_key
        if part.get("version"):
            merged["version"] = part["version"]
        merged["terms"].extend(part.get("terms") or [])
        for asset_id, study in (part.get("studies") or {}).items():
            if asset_id in merged["studies"]:
                raise SystemExit(f"duplicate curated study {asset_id} in {file}")
            merged["studies"][asset_id] = study
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply source-audited curated reader content to a V0.8.2 manifest"
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("curated", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = load(args.manifest)
    curated = load_curated(args.curated)
    paper_key = str((manifest.get("paper") or {}).get("key") or "")
    if paper_key != str(curated.get("paper_key") or ""):
        raise SystemExit(
            f"paper key mismatch: manifest={paper_key!r} curated={curated.get('paper_key')!r}"
        )

    studies = curated.get("studies") or {}
    figure_assets = [
        asset for asset in manifest.get("assets") or [] if asset.get("kind") == "figure"
    ]
    figure_ids = [str(asset.get("id") or "") for asset in figure_assets]
    missing = [asset_id for asset_id in figure_ids if asset_id not in studies]
    extra = [asset_id for asset_id in studies if asset_id not in figure_ids]
    if missing or extra:
        raise SystemExit(
            f"curated figure coverage mismatch: missing={missing} extra={extra}"
        )

    for asset in figure_assets:
        asset_id = str(asset["id"])
        value = studies[asset_id]
        panels = value.get("panels") or []
        if not panels:
            raise SystemExit(f"{asset_id}: no curated panels")
        labels = [str(panel.get("label") or "") for panel in panels]
        if any(not label for label in labels) or len(labels) != len(set(labels)):
            raise SystemExit(f"{asset_id}: empty or duplicate panel labels: {labels}")
        for field in ("overview", "conclusion", "boundary"):
            if not str(value.get(field) or "").strip():
                raise SystemExit(f"{asset_id}: missing {field}")
        for index, panel in enumerate(panels):
            for field in ("label", "title", "explanation"):
                if not str(panel.get(field) or "").strip():
                    raise SystemExit(f"{asset_id}: panel {index} missing {field}")
        asset["study"] = value

    terms = curated.get("terms") or []
    ids = [str(term.get("id") or "") for term in terms]
    if any(not term_id for term_id in ids) or len(ids) != len(set(ids)):
        raise SystemExit("curated terms contain empty or duplicate ids")
    manifest["terms"] = terms
    metadata = manifest.setdefault("paper", {}).setdefault("metadata", [])
    marker = {
        "label": "内容整理",
        "value": "逐段原文与翻译、逐图面板解读及术语表均按论文证据组织",
    }
    if marker not in metadata:
        metadata.append(marker)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    print(
        json.dumps(
            {
                "paper_key": paper_key,
                "figures_curated": len(figure_assets),
                "panels_curated": sum(
                    len((asset.get("study") or {}).get("panels") or [])
                    for asset in figure_assets
                ),
                "terms": len(terms),
                "output": str(args.output),
                "passed": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
