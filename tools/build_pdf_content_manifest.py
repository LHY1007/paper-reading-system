#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import statistics
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

import fitz


CAPTION_RE = re.compile(r"^(?:Figure|Fig\.|Extended Data Fig\.|Table|Figure S|Table S)\s*[A-Z]?\d+", re.I)
REFERENCE_HEADING_RE = re.compile(r"^(?:references|literature cited|bibliography)$", re.I)
SECTION_RE = re.compile(
    r"^(?:summary|abstract|introduction|results|discussion|methods|materials and methods|star methods|"
    r"limitations of the study|resource availability|acknowledg(?:e)?ments|author contributions|"
    r"declaration of interests|supplemental information|key resources table|quantification and statistical analysis)$",
    re.I,
)


@dataclass
class Fragment:
    page: int
    bbox: list[float]
    font_size: float
    text: str
    kind: str
    source_sha256: str


@dataclass
class Paragraph:
    id: str
    section_id: str | None
    page_start: int
    page_end: int
    source_text: str
    source_sha256: str
    fragments: list[dict]
    citation_ids: list[str]
    figure_refs: list[str]
    table_refs: list[str]
    translation_zh: str | None = None


def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def join_lines(lines: Iterable[str]) -> str:
    out = ""
    for line in lines:
        line = normalize(line)
        if not line:
            continue
        if out.endswith("-") and re.match(r"^[a-z]", line):
            out = out[:-1] + line
        else:
            out += (" " if out else "") + line
    return normalize(out)


def normalized_repeat_key(text: str) -> str:
    text = re.sub(r"\d+", "#", normalize(text))
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def collect_blocks(doc: fitz.Document) -> tuple[list[list[dict]], float, set[str]]:
    pages: list[list[dict]] = []
    font_sizes: list[float] = []
    repeated_candidates: collections.Counter[str] = collections.Counter()

    for page in doc:
        page_height = page.rect.height
        page_blocks: list[dict] = []
        for block in page.get_text("dict", sort=True).get("blocks", []):
            if block.get("type") != 0:
                continue
            lines: list[str] = []
            sizes: list[float] = []
            spans: list[dict] = []
            for line in block.get("lines", []):
                line_text = "".join(span.get("text", "") for span in line.get("spans", []))
                if line_text.strip():
                    lines.append(line_text)
                for span in line.get("spans", []):
                    text = span.get("text", "")
                    if not text.strip():
                        continue
                    size = float(span.get("size", 0))
                    sizes.append(size)
                    if 5 < size < 20:
                        font_sizes.extend([size] * max(1, min(len(text), 40)))
                    spans.append({
                        "text": text,
                        "bbox": list(span.get("bbox", (0, 0, 0, 0))),
                        "size": size,
                        "flags": int(span.get("flags", 0)),
                    })
            text = join_lines(lines)
            if not text:
                continue
            bbox = list(block.get("bbox", (0, 0, 0, 0)))
            if bbox[1] < page_height * 0.08 or bbox[3] > page_height * 0.92:
                repeated_candidates[normalized_repeat_key(text)] += 1
            page_blocks.append({
                "text": text,
                "bbox": bbox,
                "font_size": statistics.median(sizes) if sizes else 0,
                "spans": spans,
            })
        pages.append(page_blocks)

    body_size = statistics.median(font_sizes) if font_sizes else 9.0
    threshold = max(3, int(len(doc) * 0.12))
    repeated = {key for key, count in repeated_candidates.items() if count >= threshold}
    return pages, body_size, repeated


def is_reference_entry(text: str) -> bool:
    return bool(
        re.match(r"^\d+[\s.]+[A-Z]", text)
        or re.match(r"^[A-Z][A-Za-z'’-]+,\s+[A-Z]", text)
        or ("doi.org/" in text and len(text) < 1000)
    )


def classify_blocks(doc: fitz.Document, pages: list[list[dict]], body_size: float, repeated: set[str]) -> list[Fragment]:
    fragments: list[Fragment] = []
    in_references = False
    for page_number, blocks in enumerate(pages, 1):
        page_height = doc[page_number - 1].rect.height
        for block in blocks:
            text = block["text"]
            bbox = block["bbox"]
            repeat_key = normalized_repeat_key(text)
            if (bbox[1] < page_height * 0.08 or bbox[3] > page_height * 0.92) and repeat_key in repeated:
                kind = "header_footer"
            elif REFERENCE_HEADING_RE.fullmatch(text):
                in_references = True
                kind = "heading"
            elif CAPTION_RE.match(text):
                kind = "caption"
            elif SECTION_RE.fullmatch(text) or (len(text) < 160 and block["font_size"] >= body_size + 0.8):
                kind = "heading"
            elif in_references and is_reference_entry(text):
                kind = "reference"
            elif len(text) >= 40:
                kind = "body"
            else:
                kind = "other"
            fragments.append(Fragment(
                page=page_number,
                bbox=[round(float(v), 2) for v in bbox],
                font_size=round(float(block["font_size"]), 2),
                text=text,
                kind=kind,
                source_sha256=digest_text(text),
            ))
    return fragments


def column_key(fragment: Fragment, page_width: float) -> int:
    center = (fragment.bbox[0] + fragment.bbox[2]) / 2
    return 0 if center < page_width / 2 else 1


def should_merge(previous: Fragment, current: Fragment, doc: fitz.Document) -> bool:
    if previous.kind != "body" or current.kind != "body":
        return False
    if current.page - previous.page > 1:
        return False
    previous_text = previous.text.rstrip()
    current_text = current.text.lstrip()
    if not previous_text or not current_text:
        return False
    if previous.page == current.page:
        page_width = doc[previous.page - 1].rect.width
        same_column = column_key(previous, page_width) == column_key(current, page_width)
        vertical_gap = current.bbox[1] - previous.bbox[3]
        if not same_column or vertical_gap > 2.8 * max(previous.font_size, current.font_size, 8):
            return False
    elif not (previous_text.endswith("-") or re.match(r"^[a-z]", current_text)):
        return False
    if previous_text.endswith("-"):
        return True
    if re.search(r"[.!?][\"')\]]?$", previous_text):
        return False
    if re.search(r"\b(?:et al|Fig|Figs|Dr|vs)\.$", previous_text):
        return False
    return True


def merge_text(left: str, right: str) -> str:
    left = left.rstrip()
    right = right.lstrip()
    if left.endswith("-") and re.match(r"^[a-z]", right):
        return normalize(left[:-1] + right)
    return normalize(left + " " + right)


def extract_refs(text: str) -> tuple[list[str], list[str], list[str]]:
    citations: list[str] = []
    for match in re.finditer(r"(?<![\d.])(?:\(|\[)?(\d{1,3}(?:\s*[–-]\s*\d{1,3})?(?:\s*,\s*\d{1,3})*)(?:\)|\])?", text):
        token = match.group(1)
        if match.start() > 0 and text[match.start() - 1].isalnum():
            continue
        if token not in citations:
            citations.append(token)
    figures = []
    tables = []
    for match in re.finditer(r"\b(?:Figure|Fig\.)\s+([A-Z]?\d+[A-Za-z]?(?:\s*[–-]\s*[A-Z]?\d+[A-Za-z]?)?)", text, re.I):
        value = match.group(1)
        if value not in figures:
            figures.append(value)
    for match in re.finditer(r"\bTable\s+([A-Z]?\d+[A-Za-z]?)", text, re.I):
        value = match.group(1)
        if value not in tables:
            tables.append(value)
    return citations, figures, tables


def build_manifest(pdf: Path) -> dict:
    doc = fitz.open(pdf)
    pages, body_size, repeated = collect_blocks(doc)
    fragments = classify_blocks(doc, pages, body_size, repeated)

    sections: list[dict] = []
    current_section_id: str | None = None
    paragraphs_raw: list[list[Fragment]] = []
    for fragment in fragments:
        if fragment.kind == "heading":
            current_section_id = f"s-{len(sections) + 1:03d}"
            sections.append({
                "id": current_section_id,
                "title": fragment.text,
                "page": fragment.page,
                "source_sha256": fragment.source_sha256,
            })
            continue
        if fragment.kind != "body":
            continue
        if paragraphs_raw and should_merge(paragraphs_raw[-1][-1], fragment, doc):
            paragraphs_raw[-1].append(fragment)
        else:
            paragraphs_raw.append([fragment])

    paragraphs: list[Paragraph] = []
    section_index = 0
    for index, group in enumerate(paragraphs_raw, 1):
        while section_index + 1 < len(sections) and sections[section_index + 1]["page"] <= group[0].page:
            section_index += 1
        section_id = sections[section_index]["id"] if sections else None
        source_text = group[0].text
        for fragment in group[1:]:
            source_text = merge_text(source_text, fragment.text)
        citations, figures, tables = extract_refs(source_text)
        paragraphs.append(Paragraph(
            id=f"p-{index:04d}",
            section_id=section_id,
            page_start=group[0].page,
            page_end=group[-1].page,
            source_text=source_text,
            source_sha256=digest_text(source_text),
            fragments=[asdict(fragment) for fragment in group],
            citation_ids=citations,
            figure_refs=figures,
            table_refs=tables,
        ))

    counts = collections.Counter(fragment.kind for fragment in fragments)
    captions = [asdict(fragment) for fragment in fragments if fragment.kind == "caption"]
    references = [asdict(fragment) for fragment in fragments if fragment.kind == "reference"]
    return {
        "schema_version": "pdf-content-manifest-0.1",
        "status": "source_only_requires_translation_and_figure_study",
        "paper": {
            "source_pdf": pdf.name,
            "source_pdf_sha256": digest_file(pdf),
            "pages": len(doc),
            "body_font_size": round(body_size, 2),
        },
        "audit": {
            "raw_fragment_counts": dict(counts),
            "natural_paragraphs": len(paragraphs),
            "captions": len(captions),
            "references": len(references),
            "repeated_header_footer_patterns": len(repeated),
        },
        "sections": sections,
        "paragraphs": [asdict(paragraph) for paragraph in paragraphs],
        "assets": captions,
        "references": references,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a version-independent PDF-native paper content manifest")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    manifest = build_manifest(args.pdf)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({
        "output": str(args.output),
        "paragraphs": manifest["audit"]["natural_paragraphs"],
        "captions": manifest["audit"]["captions"],
        "references": manifest["audit"]["references"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
