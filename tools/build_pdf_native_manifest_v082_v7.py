#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import fitz

import build_pdf_native_manifest_v082_v6 as v6


base = v6.base
ORIGINAL_BUILD_MANIFEST = base.base.build_manifest
ORIGINAL_AUGMENT_AUDIT = base.augment_audit
FIGURE_PREFIX = re.compile(r"^(Figure|Fig\.)\s+([A-Za-z]?\d+)\.\s+", re.I)
PANEL_MARKER = re.compile(r"^\([A-Za-z](?:\s*(?:and|,|–|-)\s*[A-Za-z])?\)")
TITLE_EXPLANATION_START = re.compile(
    r"\s+(?=(?:Flowchart|Horizontal bar chart|Circular plot|Scatter plots?|Each subplot|Correlation analysis|Bar charts?|Loss curves?|Grid charts?|Case stud(?:y|ies)|Heatmaps?|Kaplan-Meier|Representative images?)\b)",
    re.I,
)
LEGEND_CONTINUED = re.compile(r"\s*\(legend continued on next page\)\s*", re.I)
RUNNING_FOOTER = re.compile(r"^(?:\d+\s+)?(?:Cell|Nature|Science)\s+\d|^Article$|^OPEN ACCESS$", re.I)


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def caption_title(caption: str) -> str | None:
    match = FIGURE_PREFIX.match(caption)
    if not match:
        return None
    remainder = caption[match.end() :]
    panel = re.search(r"\s+\([A-Za-z](?:\s*(?:and|,|–|-)\s*[A-Za-z])?\)", remainder)
    explanation = TITLE_EXPLANATION_START.search(remainder)
    stops = [value.start() for value in (panel, explanation) if value]
    if not stops:
        return None
    description = norm(remainder[: min(stops)]).rstrip(". ;:")
    if len(description) < 5:
        return None
    return norm(f"Figure {match.group(2)}. {description}")


def continued_legend(page: fitz.Page) -> str:
    candidates: list[tuple[float, float, str]] = []
    threshold = page.rect.height * 0.58
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text = block[:5]
        value = norm(text)
        if y0 < threshold or not value or RUNNING_FOOTER.match(value):
            continue
        if PANEL_MARKER.match(value):
            candidates.append((float(y0), float(x0), value))
    candidates.sort()
    return norm(" ".join(value for _, _, value in candidates))


def repair_cross_page_caption(doc: fitz.Document, asset: dict[str, Any]) -> tuple[str, bool, bool]:
    caption = norm(asset.get("caption_en"))
    marker = LEGEND_CONTINUED.search(caption)
    if not marker:
        return caption, False, True
    first = norm(caption[: marker.start()])
    source_page = int(asset.get("source_page", -1))
    next_page = source_page + 1
    if not (0 <= next_page < len(doc)):
        return first, True, False
    continuation = continued_legend(doc[next_page])
    return norm(f"{first} {continuation}"), True, bool(continuation)


def v5_panel_evidence(caption: str) -> list[dict[str, str]]:
    return v6.v5.panel_evidence_from_caption(caption)


def build_manifest_v7(pdf: Path, source: dict[str, Any], audit_path: Path | None = None) -> dict[str, Any]:
    manifest = ORIGINAL_BUILD_MANIFEST(pdf, source, audit_path)
    doc = fitz.open(pdf)
    titles_completed = 0
    cross_page_captions_rebuilt = 0
    continuation_blocks_missing: list[str] = []

    for asset in manifest.get("assets", []):
        repaired_caption, had_continuation, continuation_found = repair_cross_page_caption(doc, asset)
        if had_continuation:
            cross_page_captions_rebuilt += 1
            if not continuation_found:
                continuation_blocks_missing.append(str(asset.get("id")))
            asset["caption_en"] = repaired_caption
            panels = v5_panel_evidence(repaired_caption)
            if panels:
                study = asset.get("study") or {}
                study["panels"] = panels
                asset["study"] = study

        completed = caption_title(norm(asset.get("caption_en")))
        if completed and len(completed) > len(norm(asset.get("title_en"))):
            asset["title_en"] = completed
            titles_completed += 1

    repairs = manifest.get("evidence_repairs") or {}
    repairs["parser"] = "v082-final-7"
    repairs["titles_completed_from_caption"] = int(repairs.get("titles_completed_from_caption", 0) or 0) + titles_completed
    repairs["cross_page_captions_rebuilt"] = cross_page_captions_rebuilt
    repairs["continuation_blocks_missing"] = continuation_blocks_missing
    repairs["caption_panel_evidence_blocks"] = sum(
        len((asset.get("study") or {}).get("panels") or []) for asset in manifest.get("assets", [])
    )
    repairs["reference_count"] = len(manifest.get("references", []))
    manifest["evidence_repairs"] = repairs
    return manifest


def augment_audit_v7(audit: dict[str, Any], manifest: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    result = ORIGINAL_AUGMENT_AUDIT(audit, manifest, source)
    repairs = manifest.get("evidence_repairs") or {}
    result["strict_layout_parser"] = "v082-final-7"
    result["references"] = len(manifest.get("references", []))
    result["assets"] = len(manifest.get("assets", []))
    result["titles_completed_from_caption"] = repairs.get("titles_completed_from_caption")
    result["cross_page_captions_rebuilt"] = repairs.get("cross_page_captions_rebuilt")
    result["continuation_blocks_missing"] = repairs.get("continuation_blocks_missing")
    result["caption_panel_evidence_blocks"] = repairs.get("caption_panel_evidence_blocks")
    result["tables_reconstructed"] = repairs.get("tables_reconstructed")
    result["reference_repair_applied"] = repairs.get("reference_repair_applied")
    return result


base.base.build_manifest = build_manifest_v7
base.augment_audit = augment_audit_v7


def main() -> None:
    base.main()


if __name__ == "__main__":
    main()
