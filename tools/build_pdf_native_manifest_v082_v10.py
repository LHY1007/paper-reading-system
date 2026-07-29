#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import fitz

import build_pdf_native_manifest_v082_v9 as v9


base = v9.base
ORIGINAL_BUILD_MANIFEST = base.base.build_manifest
ORIGINAL_AUGMENT_AUDIT = base.augment_audit
MONTH_DATE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b"
)
GROUP_AUTHOR = re.compile(r"\b(The\s+[^\n]{3,140}?Consortium\s*\([A-Z][A-Z0-9-]+\))")


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def published_date(doc: fitz.Document) -> str:
    if not len(doc):
        return ""
    text = doc[0].get_text("text")
    dates = MONTH_DATE.findall(text)
    matches = list(MONTH_DATE.finditer(text))
    if not matches:
        return ""
    return matches[-1].group(0)


def group_authors(doc: fitz.Document) -> list[str]:
    found: list[str] = []
    for page_index in range(len(doc)):
        text = doc[page_index].get_text("text")
        for match in GROUP_AUTHOR.finditer(text):
            value = norm(match.group(1))
            if value not in found:
                found.append(value)
    return found


def build_manifest_v10(pdf: Path, source: dict[str, Any], audit_path: Path | None = None) -> dict[str, Any]:
    manifest = ORIGINAL_BUILD_MANIFEST(pdf, source, audit_path)
    doc = fitz.open(pdf)
    paper = manifest.get("paper") or {}
    authors = list(paper.get("authors") or [])
    groups = group_authors(doc)
    for group in groups:
        if group in authors:
            continue
        insert_at = max(0, len(authors) - 1) if authors else 0
        authors.insert(insert_at, group)
    if authors:
        paper["authors"] = authors

    fallback_date = ""
    if not norm(paper.get("publication_timeline")):
        fallback_date = published_date(doc)
        if fallback_date:
            paper["publication_timeline"] = f"Published: {fallback_date}"
    manifest["paper"] = paper

    repairs = manifest.get("evidence_repairs") or {}
    repairs["parser"] = "v082-final-10"
    repairs["group_authors_extracted"] = groups
    repairs["authors_extracted"] = len(authors)
    repairs["publication_date_fallback"] = fallback_date
    repairs["publication_timeline_extracted"] = bool(norm(paper.get("publication_timeline")))
    repairs["reference_count"] = len(manifest.get("references", []))
    manifest["evidence_repairs"] = repairs
    return manifest


def augment_audit_v10(audit: dict[str, Any], manifest: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    result = ORIGINAL_AUGMENT_AUDIT(audit, manifest, source)
    repairs = manifest.get("evidence_repairs") or {}
    result["strict_layout_parser"] = "v082-final-10"
    result["references"] = len(manifest.get("references", []))
    result["assets"] = len(manifest.get("assets", []))
    result["authors_extracted"] = repairs.get("authors_extracted")
    result["affiliations_extracted"] = repairs.get("affiliations_extracted")
    result["group_authors_extracted"] = repairs.get("group_authors_extracted")
    result["publication_timeline_extracted"] = repairs.get("publication_timeline_extracted")
    result["continuation_blocks_missing"] = repairs.get("continuation_blocks_missing")
    result["tables_reconstructed"] = repairs.get("tables_reconstructed")
    result["reference_repair_applied"] = repairs.get("reference_repair_applied")
    return result


base.base.build_manifest = build_manifest_v10
base.augment_audit = augment_audit_v10


def main() -> None:
    base.main()


if __name__ == "__main__":
    main()
