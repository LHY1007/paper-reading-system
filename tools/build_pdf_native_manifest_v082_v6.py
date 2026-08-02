#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import fitz

import build_pdf_native_manifest_v082_v5 as v5


base = v5.base
ORIGINAL_BUILD_MANIFEST = base.base.build_manifest
ORIGINAL_AUGMENT_AUDIT = base.augment_audit
CAPTION_TITLE = re.compile(
    r"^(Figure|Fig\.)\s+([A-Za-z]?\d+)\.\s+(.{5,400}?)(?=\s+\((?:[A-Za-z])(?:\s*(?:and|,|–|-)\s*[A-Za-z])?\))",
    re.I | re.S,
)
TABLE_ID = re.compile(r"^table-(\d+)$", re.I)


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def external_headers(page: fitz.Page, table: Any) -> list[str]:
    rows = getattr(table, "rows", [])
    if not rows or not rows[0].cells:
        return []
    first_cells = rows[0].cells
    bbox = table.bbox
    band_top = max(0.0, bbox[1] - 20.0)
    band_bottom = bbox[1] - 0.5
    words = [
        word
        for word in page.get_text("words")
        if word[1] >= band_top
        and word[3] <= band_bottom + 1.5
        and word[0] >= bbox[0] - 2
        and word[2] <= bbox[2] + 2
    ]
    headers: list[str] = []
    for cell in first_cells:
        if cell is None:
            headers.append("")
            continue
        x0, _, x1, _ = cell
        cell_words = [word for word in words if (word[0] + word[2]) / 2 >= x0 and (word[0] + word[2]) / 2 < x1]
        cell_words.sort(key=lambda word: (round(word[1], 1), word[0]))
        headers.append(norm(" ".join(word[4] for word in cell_words)))
    return headers if headers and all(headers) else []


def table_payload(page: fitz.Page) -> dict[str, Any] | None:
    try:
        finder = page.find_tables()
    except Exception:
        return None
    tables = list(getattr(finder, "tables", []) or [])
    if not tables:
        return None
    table = max(tables, key=lambda item: len(item.extract() or []))
    data = table.extract() or []
    if not data or not data[0]:
        return None
    rows = [[norm(cell) for cell in row] for row in data]
    column_count = max(len(row) for row in rows)
    rows = [row + [""] * (column_count - len(row)) for row in rows]
    headers = external_headers(page, table)
    if not headers:
        detected = [norm(value) for value in getattr(table.header, "names", [])]
        if getattr(table.header, "external", False) and len(detected) == column_count and all(detected):
            headers = detected
        else:
            headers = [f"Column {index + 1}" for index in range(column_count)]
    return {
        "headers": headers,
        "rows": rows,
        "source_bbox": [round(float(value), 3) for value in table.bbox],
        "source_detection": "PyMuPDF page.find_tables with external-header recovery",
    }


def build_manifest_v6(pdf: Path, source: dict[str, Any], audit_path: Path | None = None) -> dict[str, Any]:
    manifest = ORIGINAL_BUILD_MANIFEST(pdf, source, audit_path)
    doc = fitz.open(pdf)
    titles_completed = 0
    tables_reconstructed = 0
    table_fallbacks = 0

    for asset in manifest.get("assets", []):
        caption = norm(asset.get("caption_en"))
        title_match = CAPTION_TITLE.match(caption)
        if title_match:
            number = title_match.group(2)
            description = norm(title_match.group(3)).rstrip(".")
            expected_prefix = "Figure" if not number.upper().startswith("S") else "Figure"
            completed = norm(f"{expected_prefix} {number}. {description}")
            if len(completed) > len(norm(asset.get("title_en"))):
                asset["title_en"] = completed
                titles_completed += 1

        table_match = TABLE_ID.fullmatch(str(asset.get("id") or ""))
        if not table_match:
            continue
        source_page = int(asset.get("source_page", -1))
        payload = table_payload(doc[source_page]) if 0 <= source_page < len(doc) else None
        if payload and payload.get("rows"):
            asset["kind"] = "table"
            asset["table"] = {
                "headers": payload["headers"],
                "rows": payload["rows"],
            }
            asset["source_render"] = payload["source_detection"]
            asset["table_source_bbox"] = payload["source_bbox"]
            tables_reconstructed += 1
        else:
            table_fallbacks += 1

    repairs = manifest.get("evidence_repairs") or {}
    repairs["parser"] = "v082-final-6"
    repairs["titles_completed_from_caption"] = titles_completed
    repairs["tables_reconstructed"] = tables_reconstructed
    repairs["table_image_fallbacks"] = table_fallbacks
    repairs["reference_count"] = len(manifest.get("references", []))
    manifest["evidence_repairs"] = repairs
    return manifest


def augment_audit_v6(audit: dict[str, Any], manifest: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    result = ORIGINAL_AUGMENT_AUDIT(audit, manifest, source)
    repairs = manifest.get("evidence_repairs") or {}
    result["strict_layout_parser"] = "v082-final-6"
    result["references"] = len(manifest.get("references", []))
    result["assets"] = len(manifest.get("assets", []))
    result["titles_completed_from_caption"] = repairs.get("titles_completed_from_caption")
    result["tables_reconstructed"] = repairs.get("tables_reconstructed")
    result["table_image_fallbacks"] = repairs.get("table_image_fallbacks")
    result["reference_repair_applied"] = repairs.get("reference_repair_applied")
    return result


base.base.build_manifest = build_manifest_v6
base.augment_audit = augment_audit_v6


def main() -> None:
    base.main()


if __name__ == "__main__":
    main()
