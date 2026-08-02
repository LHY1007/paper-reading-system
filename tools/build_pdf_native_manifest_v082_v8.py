#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import fitz

import build_pdf_native_manifest_v082_v7 as v7


base = v7.base
ORIGINAL_BUILD_MANIFEST = base.base.build_manifest
ORIGINAL_AUGMENT_AUDIT = base.augment_audit
LEGEND_MARKER = re.compile(r"\(legend continued on next page\)", re.I)


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def title_search_key(asset: dict[str, Any]) -> str:
    title = norm(asset.get("title_en"))
    if len(title) <= 120:
        return title
    return title[:120].rsplit(" ", 1)[0]


def locate_caption_start(doc: fitz.Document, asset: dict[str, Any]) -> tuple[int, str] | None:
    key = title_search_key(asset)
    if not key:
        return None
    for page_index in range(len(doc)):
        text = norm(doc[page_index].get_text("text"))
        position = text.find(key)
        if position >= 0:
            return page_index, text[position:]
    return None


def rebuild_cross_page_caption(doc: fitz.Document, asset: dict[str, Any]) -> tuple[str | None, bool]:
    located = locate_caption_start(doc, asset)
    if located is None:
        return None, False
    page_index, tail = located
    marker = LEGEND_MARKER.search(tail)
    if marker is None:
        return None, False
    first = norm(tail[: marker.start()])
    next_page = page_index + 1
    if next_page >= len(doc):
        return first, False
    continuation = v7.continued_legend(doc[next_page])
    if not continuation:
        return first, False
    return norm(f"{first} {continuation}"), True


def panel_evidence(caption: str) -> list[dict[str, str]]:
    return v7.v5_panel_evidence(caption)


def build_manifest_v8(pdf: Path, source: dict[str, Any], audit_path: Path | None = None) -> dict[str, Any]:
    manifest = ORIGINAL_BUILD_MANIFEST(pdf, source, audit_path)
    doc = fitz.open(pdf)
    repairs = manifest.get("evidence_repairs") or {}
    missing = set(str(value) for value in repairs.get("continuation_blocks_missing") or [])
    rebuilt_ids: list[str] = []
    still_missing: list[str] = []

    for asset in manifest.get("assets", []):
        asset_id = str(asset.get("id") or "")
        if asset_id not in missing:
            continue
        rebuilt, complete = rebuild_cross_page_caption(doc, asset)
        if rebuilt:
            asset["caption_en"] = rebuilt
            panels = panel_evidence(rebuilt)
            if panels:
                study = asset.get("study") or {}
                study["panels"] = panels
                asset["study"] = study
        if complete:
            rebuilt_ids.append(asset_id)
        else:
            still_missing.append(asset_id)

    repairs["parser"] = "v082-final-8"
    repairs["cross_page_captions_rebuilt_by_title_lookup"] = rebuilt_ids
    repairs["continuation_blocks_missing"] = still_missing
    repairs["caption_panel_evidence_blocks"] = sum(
        len((asset.get("study") or {}).get("panels") or []) for asset in manifest.get("assets", [])
    )
    repairs["reference_count"] = len(manifest.get("references", []))
    manifest["evidence_repairs"] = repairs
    return manifest


def augment_audit_v8(audit: dict[str, Any], manifest: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    result = ORIGINAL_AUGMENT_AUDIT(audit, manifest, source)
    repairs = manifest.get("evidence_repairs") or {}
    result["strict_layout_parser"] = "v082-final-8"
    result["references"] = len(manifest.get("references", []))
    result["assets"] = len(manifest.get("assets", []))
    result["cross_page_captions_rebuilt_by_title_lookup"] = repairs.get("cross_page_captions_rebuilt_by_title_lookup")
    result["continuation_blocks_missing"] = repairs.get("continuation_blocks_missing")
    result["caption_panel_evidence_blocks"] = repairs.get("caption_panel_evidence_blocks")
    result["tables_reconstructed"] = repairs.get("tables_reconstructed")
    result["reference_repair_applied"] = repairs.get("reference_repair_applied")
    return result


base.base.build_manifest = build_manifest_v8
base.augment_audit = augment_audit_v8


def main() -> None:
    base.main()


if __name__ == "__main__":
    main()
