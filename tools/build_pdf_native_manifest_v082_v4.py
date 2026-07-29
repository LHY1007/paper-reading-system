#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import fitz

import build_pdf_native_manifest_v082_v3 as v3


base = v3.base
ORIGINAL_BUILD_MANIFEST = base.base.build_manifest
ORIGINAL_AUGMENT_AUDIT = base.augment_audit
REFERENCE_LINE = re.compile(r"(?m)^(\d{1,3})\.\s+")
REFERENCE_STOP = re.compile(
    r"(?m)^(?:Author information|Methods|Acknowledgements|Author contributions|Competing interests|Additional information|Extended data)\s*$",
    re.I,
)
FIGURE_TOC = re.compile(r"^(Fig\.|Figure|Extended Data Fig\.|Supplementary Fig\.)\s*(\d+)[.]?\s*(.*)$", re.I)
PANEL_START = re.compile(r"(?:^|\s)([a-z])[,)]\s+(?=[A-Z0-9])")
RUNNING_HEADER = re.compile(
    r"\s+(?:Nature Genetics|Nature Medicine|Nature Machine Intelligence|Nature Communications|Cell)\s*(?:\||\d).*$",
    re.I | re.S,
)


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def source_outline(doc: fitz.Document) -> list[dict[str, Any]]:
    outline: list[dict[str, Any]] = []
    for level, title, page in doc.get_toc(simple=True):
        title = norm(title)
        if not title:
            continue
        kind = "figure" if FIGURE_TOC.match(title) else "section"
        if title.lower() in {"online content", "check for updates"}:
            kind = "administrative"
        outline.append({"level": int(level), "title": title, "page": int(page), "kind": kind})
    return outline


def figure_title_index(outline: list[dict[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for item in outline:
        match = FIGURE_TOC.match(item["title"])
        if not match:
            continue
        family = match.group(1).lower()
        number = int(match.group(2))
        description = norm(match.group(3)).rstrip(".")
        if family.startswith("extended"):
            asset_id = f"extended-data-figure-{number}"
            prefix = f"Extended Data Figure {number}."
        elif family.startswith("supplementary"):
            asset_id = f"supplementary-figure-{number}"
            prefix = f"Supplementary Figure {number}."
        else:
            asset_id = f"figure-{number}"
            prefix = f"Figure {number}."
        index[asset_id] = norm(f"{prefix} {description}")
    return index


def section_heading_candidates(outline: list[dict[str, Any]]) -> list[str]:
    candidates: list[str] = []
    for item in outline:
        if item["kind"] != "section":
            continue
        title = norm(item["title"])
        if len(title) < 5 or title.lower() in {"results", "discussion"}:
            continue
        candidates.append(title)
    return sorted(set(candidates), key=len, reverse=True)


def clean_caption(caption: str, headings: list[str]) -> str:
    caption = norm(caption)
    if not caption:
        return caption
    stop_positions: list[int] = []
    for heading in headings:
        position = caption.find(heading, 160)
        if position >= 0:
            stop_positions.append(position)
    header_match = RUNNING_HEADER.search(caption)
    if header_match:
        stop_positions.append(header_match.start())
    if stop_positions:
        caption = caption[: min(stop_positions)]
    return norm(caption)


def caption_panel_evidence(caption: str) -> list[dict[str, str]]:
    matches = list(PANEL_START.finditer(caption))
    panels: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(caption)
        text = norm(caption[start:end])
        if len(text) < 12:
            continue
        panels.append({"label": match.group(1).upper(), "source_text": text})
    return panels


def numbered_references(doc: fitz.Document, expected: int) -> list[dict[str, str]]:
    if expected <= 0:
        return []
    records: dict[int, str] = {}
    previous_number: int | None = None
    previous_page: int | None = None
    previous_open = False

    for page_index in range(len(doc)):
        text = doc[page_index].get_text("text")
        matches = list(REFERENCE_LINE.finditer(text))
        accepted = [match for match in matches if 1 <= int(match.group(1)) <= expected]
        if not accepted:
            previous_open = False
            continue

        numbers = [int(match.group(1)) for match in accepted]
        is_sequence_page = any(
            number == 1 or (previous_number is not None and number == previous_number + 1)
            for number in numbers
        )
        if not is_sequence_page:
            previous_open = False
            continue

        first = accepted[0]
        if (
            previous_open
            and previous_number is not None
            and previous_page is not None
            and page_index == previous_page + 1
            and int(first.group(1)) == previous_number + 1
        ):
            continuation = norm(text[: first.start()])
            if continuation:
                records[previous_number] = norm(records.get(previous_number, "") + " " + continuation)

        for index, match in enumerate(accepted):
            number = int(match.group(1))
            if number != 1 and previous_number is not None and number != previous_number + 1:
                continue
            start = match.end()
            end = accepted[index + 1].start() if index + 1 < len(accepted) else len(text)
            segment = text[start:end]
            stop = REFERENCE_STOP.search(segment)
            closed = False
            if stop:
                segment = segment[: stop.start()]
                closed = True
            records[number] = norm(segment)
            previous_number = number
            previous_page = page_index
            previous_open = not closed and index == len(accepted) - 1

    if sorted(records) != list(range(1, expected + 1)):
        return []
    references: list[dict[str, str]] = []
    for number in range(1, expected + 1):
        text = records[number]
        if len(text) < 20:
            return []
        references.append({"id": str(number), "text": text})
    return references


def build_manifest_v4(pdf: Path, source: dict[str, Any], audit_path: Path | None = None) -> dict[str, Any]:
    manifest = ORIGINAL_BUILD_MANIFEST(pdf, source, audit_path)
    doc = fitz.open(pdf)
    outline = source_outline(doc)
    title_index = figure_title_index(outline)
    headings = section_heading_candidates(outline)

    manifest["paper"]["key"] = source.get("key") or manifest["paper"].get("key")
    manifest["evidence_outline"] = outline
    manifest["evidence_front_matter"] = {
        "first_page_text": norm(doc[0].get_text("text"))[:12000] if len(doc) else "",
        "author_information_pages": [
            {"page": page + 1, "text": norm(doc[page].get_text("text"))[:16000]}
            for page in range(len(doc))
            if "A full list of affiliations" in doc[page].get_text("text")
            or "Author information" in doc[page].get_text("text")
        ][:4],
    }

    corrected_titles = 0
    cleaned_captions = 0
    source_panels = 0
    for asset in manifest.get("assets", []):
        asset_id = str(asset.get("id") or "")
        if asset_id in title_index:
            if norm(asset.get("title_en")) != title_index[asset_id]:
                corrected_titles += 1
            asset["title_en"] = title_index[asset_id]
        before = norm(asset.get("caption_en"))
        after = clean_caption(before, headings)
        if after != before:
            cleaned_captions += 1
        asset["caption_en"] = after
        study = asset.get("study") or {}
        panels = caption_panel_evidence(after)
        source_panels += len(panels)
        study["panels"] = panels
        asset["study"] = study

    expected_references = int(source.get("expected_reference_count", 0) or 0)
    repaired_references = numbered_references(doc, expected_references)
    reference_repair_applied = bool(repaired_references)
    if repaired_references:
        manifest["references"] = repaired_references

    manifest["evidence_repairs"] = {
        "parser": "v082-final-4",
        "toc_entries": len(outline),
        "figure_titles_corrected": corrected_titles,
        "captions_trimmed_at_section_or_running_header": cleaned_captions,
        "caption_panel_evidence_blocks": source_panels,
        "reference_repair_applied": reference_repair_applied,
        "reference_count": len(manifest.get("references", [])),
        "expected_reference_count": expected_references,
    }
    return manifest


def augment_audit_v4(audit: dict[str, Any], manifest: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    result = ORIGINAL_AUGMENT_AUDIT(audit, manifest, source)
    repairs = manifest.get("evidence_repairs") or {}
    result["strict_layout_parser"] = "v082-final-4"
    result["source_outline_entries"] = repairs.get("toc_entries")
    result["figure_titles_corrected_from_pdf_toc"] = repairs.get("figure_titles_corrected")
    result["captions_trimmed"] = repairs.get("captions_trimmed_at_section_or_running_header")
    result["caption_panel_evidence_blocks"] = repairs.get("caption_panel_evidence_blocks")
    result["reference_repair_applied"] = repairs.get("reference_repair_applied")
    result["reader_content_status"] = "evidence-only; requires paper-specific reader content task and completed bilingual manifest"
    return result


base.base.build_manifest = build_manifest_v4
base.augment_audit = augment_audit_v4


def main() -> None:
    base.main()


if __name__ == "__main__":
    main()
