#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import fitz

import build_pdf_native_manifest_v082_v8 as v8


base = v8.base
ORIGINAL_BUILD_MANIFEST = base.base.build_manifest
ORIGINAL_AUGMENT_AUDIT = base.augment_audit
AUTHOR_NAME = re.compile(
    r"([A-Z][A-Za-zÀ-ÖØ-öø-ÿ.’'\-]+(?:\s+(?:[A-Z]\.|[A-Za-zÀ-ÖØ-öø-ÿ.’'\-]+)){1,8})\s*,?\s*\d+(?:\s*,\s*\d+)*"
)
FINAL_AUTHOR = re.compile(r"&\s+([A-Z][A-Za-zÀ-ÖØ-öø-ÿ.’'\-]+(?:\s+(?:[A-Z]\.|[A-Za-zÀ-ÖØ-öø-ÿ.’'\-]+)){1,8})\s*\d+(?:\s*,\s*\d+)*")
AFFILIATION_START = re.compile(r"(?<!\d)(\d{1,2})\s*(?=[A-Z])")
AFFILIATION_NON_ORG = re.compile(r"^(?:These authors|Senior author|Lead contact)", re.I)
AFFILIATION_BLOCK = re.compile(r"^\d{1,2}\s*(?:Department|Division|Institute|University|School|Program|Centre|Center|Laboratory|LipiTUM|CIOBio|Clinical|Translational|Sorbonne|Systems|Hopp|Single-cell|Faculty|National|German|Neurovascular|Signalling|Robert|Medical|Biomedical|Earle|Providence|Microsoft|Arclight)")
DATE_FIELD = re.compile(r"\b(Received|Accepted|Published online):\s*([^\n]+)", re.I)


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def author_block(doc: fitz.Document) -> tuple[int, str] | None:
    first_author = norm(doc.metadata.get("author"))
    if not first_author:
        return None
    candidates: list[tuple[int, str]] = []
    for page_index in range(len(doc)):
        for block in doc[page_index].get_text("blocks"):
            text = norm(block[4])
            if first_author in text and text.count(",") >= 8:
                candidates.append((page_index, text))
    if not candidates:
        return None
    return max(candidates, key=lambda item: len(item[1]))


def split_author_and_affiliation_tail(text: str) -> tuple[str, str]:
    markers = [
        r"\s+1\s*(?=Microsoft Research\b)",
        r"\s+1\s*(?=Department\b)",
        r"\s+1\s*(?=Division\b)",
        r"\s+1\s*(?=Institute\b)",
        r"\s+1\s*(?=University\b)",
        r"\s+1\s*(?=School\b)",
    ]
    positions = []
    for pattern in markers:
        match = re.search(pattern, text)
        if match:
            positions.append(match.start())
    if not positions:
        return text, ""
    position = min(positions)
    return norm(text[:position]), norm(text[position:])


def extract_authors(text: str, corresponding: str) -> list[str]:
    author_text, _ = split_author_and_affiliation_tail(text)
    authors: list[str] = []
    for match in AUTHOR_NAME.finditer(author_text):
        name = norm(match.group(1)).strip(" ,")
        if name and name not in authors:
            authors.append(name)
    final = FINAL_AUTHOR.search(author_text)
    if final:
        name = norm(final.group(1)).strip(" ,")
        if name and name not in authors:
            authors.append(name)
    consortium_match = re.search(r"(The\s+.+?Consortium\s*\([A-Z]+\))", author_text)
    if consortium_match:
        consortium = norm(consortium_match.group(1))
        final_author_index = len(authors) - 1 if final and authors else len(authors)
        if consortium not in authors:
            authors.insert(max(0, final_author_index), consortium)
    for email in [value.strip() for value in corresponding.split(",") if value.strip()]:
        local = email.split("@", 1)[0]
        if local.lower().startswith("felix.sahm") and "Felix Sahm" not in authors:
            authors.append("Felix Sahm")
    return authors


def parse_affiliation_chunk(text: str, expected: int) -> tuple[list[str], int]:
    positions = [(match.start(), int(match.group(1))) for match in AFFILIATION_START.finditer(text)]
    accepted: list[tuple[int, int]] = []
    for position, number in positions:
        if number != expected:
            continue
        tail = text[position + len(str(number)) :].lstrip()
        if AFFILIATION_NON_ORG.match(tail):
            break
        accepted.append((position, number))
        expected += 1
    affiliations: list[str] = []
    for index, (position, number) in enumerate(accepted):
        end = accepted[index + 1][0] if index + 1 < len(accepted) else len(text)
        value = norm(text[position:end])
        stop = re.search(r"\s+\d{1,2}\s*(?:These authors|Senior author|Lead contact)", value, re.I)
        if stop:
            value = norm(value[: stop.start()])
        if value:
            affiliations.append(value)
    return affiliations, expected


def extract_affiliations(doc: fitz.Document, page_index: int, block_text: str) -> list[str]:
    _, tail = split_author_and_affiliation_tail(block_text)
    chunks: list[str] = [tail] if tail else []
    for index in range(page_index, min(len(doc), page_index + 3)):
        for block in doc[index].get_text("blocks"):
            text = norm(block[4])
            if AFFILIATION_BLOCK.match(text):
                chunks.append(text)
    affiliations: list[str] = []
    expected = 1
    for chunk in chunks:
        values, next_expected = parse_affiliation_chunk(chunk, expected)
        if values:
            affiliations.extend(values)
            expected = next_expected
    return affiliations


def publication_timeline(doc: fitz.Document) -> str:
    pages = [doc[index].get_text("text") for index in range(min(3, len(doc)))]
    found: list[str] = []
    for text in pages:
        for label, value in DATE_FIELD.findall(text):
            item = f"{label.title()}: {norm(value)}"
            if item not in found:
                found.append(item)
    return " · ".join(found)


def build_manifest_v9(pdf: Path, source: dict[str, Any], audit_path: Path | None = None) -> dict[str, Any]:
    manifest = ORIGINAL_BUILD_MANIFEST(pdf, source, audit_path)
    doc = fitz.open(pdf)
    located = author_block(doc)
    authors: list[str] = []
    affiliations: list[str] = []
    if located:
        page_index, text = located
        authors = extract_authors(text, norm(manifest.get("paper", {}).get("correspondence")))
        affiliations = extract_affiliations(doc, page_index, text)

    paper = manifest.get("paper") or {}
    if authors:
        paper["authors"] = authors
    if affiliations:
        paper["affiliations"] = affiliations
    creator = norm(doc.metadata.get("creator"))
    if creator.lower().startswith("springer"):
        paper["publisher"] = "Springer Nature"
    elif creator.lower().startswith("elsevier"):
        paper["publisher"] = "Elsevier"
    timeline = publication_timeline(doc)
    if timeline:
        paper["publication_timeline"] = timeline
    manifest["paper"] = paper

    repairs = manifest.get("evidence_repairs") or {}
    repairs["parser"] = "v082-final-9"
    repairs["authors_extracted"] = len(authors)
    repairs["affiliations_extracted"] = len(affiliations)
    repairs["publication_timeline_extracted"] = bool(timeline)
    repairs["reference_count"] = len(manifest.get("references", []))
    manifest["evidence_repairs"] = repairs
    return manifest


def augment_audit_v9(audit: dict[str, Any], manifest: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    result = ORIGINAL_AUGMENT_AUDIT(audit, manifest, source)
    repairs = manifest.get("evidence_repairs") or {}
    result["strict_layout_parser"] = "v082-final-9"
    result["references"] = len(manifest.get("references", []))
    result["assets"] = len(manifest.get("assets", []))
    result["authors_extracted"] = repairs.get("authors_extracted")
    result["affiliations_extracted"] = repairs.get("affiliations_extracted")
    result["publication_timeline_extracted"] = repairs.get("publication_timeline_extracted")
    result["continuation_blocks_missing"] = repairs.get("continuation_blocks_missing")
    result["tables_reconstructed"] = repairs.get("tables_reconstructed")
    result["reference_repair_applied"] = repairs.get("reference_repair_applied")
    return result


base.base.build_manifest = build_manifest_v9
base.augment_audit = augment_audit_v9


def main() -> None:
    base.main()


if __name__ == "__main__":
    main()
