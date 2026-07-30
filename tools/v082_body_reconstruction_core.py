#!/usr/bin/env python3
from __future__ import annotations

import collections
import re
import statistics
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz

import build_pdf_native_manifest_v082_v10 as v10

base = v10.base
ORIGINAL_BUILD_MANIFEST = base.base.build_manifest
ORIGINAL_AUGMENT_AUDIT = base.augment_audit
u = base.base

WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿΑ-Ωα-ω][A-Za-zÀ-ÖØ-öø-ÿΑ-Ωα-ω0-9'’\-]*")
META_RE = re.compile(
    r"^(?:https?://doi\.org/|Article\b|Research Article\b|Received:|Accepted:|Published(?: online)?:|"
    r"Check for updates|A list of authors|Full article and list of author affiliations|Correspondence\b|Corresponding authors?:|"
    r"e-mail:|Open access$|OPEN ACCESS$|Publisher’s note|This is an open access article|Downloaded from )",
    re.I,
)
AFFILIATION_RE = re.compile(
    r"^\d{1,2}\s*(?:Department|Division|Institute|University|School|Program|Centre|Center|Laboratory|"
    r"LipiTUM|CIOBio|Clinical|Translational|Sorbonne|Systems|Hopp|Single-cell|Faculty|National|German|"
    r"Neurovascular|Signalling|Robert|Medical|Biomedical|Earle|Providence|Microsoft|Arclight)\b",
    re.I,
)
REFERENCE_LINE_RE = re.compile(r"^(?:\d{1,3}\.|\d{1,3}\s+)[A-Z][A-Za-zÀ-ÖØ-öø-ÿ’\-]+")
FIGURE_LABEL_RE = re.compile(
    r"^(?:[a-z]\s+)?(?:UMAP|Expression|Fraction|Chromosome|Ben[-−]|MC |MG |WHO grade|Proportion|Percent|"
    r"Subgraph|Dominant |Neoplastic |Stromal |Endothelial|Glioneural|Microglia|Unknown|Clear cell|"
    r"Proliferative|Immunogenic|Inflammatory|High|Low|Male|Female|Sample|Patient|Data|Group|Time point|"
    r"TIME marker|REAGENT or RESOURCE)\b",
    re.I,
)
METHOD_TOC_RE = re.compile(r"^[•○\s]*(?:KEY RESOURCES TABLE|METHOD DETAILS|QUANTIFICATION AND STATISTICAL ANALYSIS).*(?:[•○].*){1,}", re.I)

ADMIN_HEADINGS = {
    "online content",
    "references",
    "references and notes",
    "bibliography",
    "literature cited",
    "key resources table",
}
COMMON_HEADINGS = [
    "Research Article Summary",
    "Summary",
    "Abstract",
    "Introduction",
    "Results",
    "Discussion",
    "Methods",
    "STAR Methods",
    "Materials and methods",
    "Limitations of the study",
    "Resource availability",
    "Lead contact",
    "Materials availability",
    "Data and code availability",
    "Data availability",
    "Code availability",
    "Acknowledgements",
    "Acknowledgments",
    "Author contributions",
    "Declaration of interests",
    "Competing interests",
    "Additional information",
    "References",
    "Online content",
    "Key resources table",
    "Quantification and statistical analysis",
    "Additional resources",
]


def norm(value: Any) -> str:
    return u.norm(str(value or ""))


def heading_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", norm(value)).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def normalize_heading_title(value: Any) -> str:
    text = norm(value).strip("•○ ")
    replacements = {
        "ISpatial autocorrelation Moran’s": "Spatial autocorrelation: Moran’s I",
        "ISpatial autocorrelation Moran's": "Spatial autocorrelation: Moran’s I",
        "Details of pathological staging and surival analysis using virtual population": "Details of pathological staging and survival analysis using virtual population",
    }
    return replacements.get(text, text)


def words(value: Any) -> list[str]:
    return WORD_RE.findall(norm(value))


def token_counter(value: Any) -> collections.Counter[str]:
    return collections.Counter(token.lower() for token in words(value))


def token_recall(source: Any, target: Any) -> float:
    left = token_counter(source)
    right = token_counter(target)
    total = sum(left.values())
    if not total:
        return 0.0
    return sum(min(count, right[token]) for token, count in left.items()) / total


def compact(value: Any) -> str:
    return re.sub(r"\W+", "", norm(value)).lower()


@dataclass
class Heading:
    title: str
    page: int
    level: int


@dataclass
class BodyEvent:
    section: str
    page: int
    text: str
    block: u.Block
    citations: list[str]
    source_pages: list[int]


def heading_candidates(manifest: dict[str, Any]) -> list[Heading]:
    items: list[Heading] = []
    seen: set[str] = set()
    for entry in manifest.get("evidence_outline", []):
        if entry.get("kind") not in {"section", "administrative"}:
            continue
        title = norm(entry.get("title")).replace("STAR★Methods", "STAR Methods")
        key = heading_key(title)
        if not title or not key or title.lower().endswith(".pdf"):
            continue
        if key in seen:
            continue
        seen.add(key)
        items.append(Heading(title, int(entry.get("page") or 0), int(entry.get("level") or 2)))
    for title in COMMON_HEADINGS:
        key = heading_key(title)
        if key not in seen:
            seen.add(key)
            items.append(Heading(title, 0, 2))
    return sorted(items, key=lambda item: len(item.title), reverse=True)


def split_heading_prefix(text: str, candidates: list[Heading]) -> tuple[Heading | None, str]:
    value = norm(text)
    value_key = heading_key(value)
    for candidate in candidates:
        title = norm(candidate.title)
        key = heading_key(title)
        if not key:
            continue
        if value.lower() == title.lower():
            return candidate, ""
        if value.lower().startswith(title.lower() + " "):
            return candidate, norm(value[len(title) :])
        if len(title) <= 120 and value_key.startswith(key + " "):
            count = len(title.split())
            parts = value.split()
            return candidate, norm(" ".join(parts[count:]))
    return None, value


def author_like(text: str, authors: list[str]) -> bool:
    value = norm(text)
    if not value:
        return False
    comma_count = value.count(",")
    affiliation_tokens = 0
    for match in re.findall(r"\b\d+(?:,\d+){1,4}\b", value):
        parts = [int(part) for part in match.split(",")]
        if all(part <= 100 for part in parts):
            affiliation_tokens += 1
    if comma_count >= 8 and affiliation_tokens >= 4:
        return True
    surnames = []
    for author in authors:
        parts = norm(author).split()
        if parts:
            surnames.append(parts[-1].strip(".,*✉"))
    hits = sum(1 for surname in surnames if len(surname) >= 4 and re.search(rf"\b{re.escape(surname)}\b", value))
    threshold = max(8, min(16, max(1, len(authors) // 6)))
    return comma_count >= 6 and affiliation_tokens >= 2 and hits >= threshold


def nonbody_corpus(manifest: dict[str, Any]) -> list[str]:
    corpus: list[str] = []
    corpus.extend(norm(item.get("text")) for item in manifest.get("references", []))
    paper = manifest.get("paper") or {}
    corpus.extend(norm(value) for value in paper.get("affiliations", []))
    corpus.extend(norm(value) for value in paper.get("authors", []))
    corpus.extend([norm(paper.get("title_en")), norm(paper.get("correspondence"))])
    return [item for item in corpus if item]


def represented_by_nonbody(text: str, corpus: list[str]) -> bool:
    value = norm(text)
    compact_value = compact(value)
    if not compact_value:
        return False
    value_words = len(words(value))
    for item in corpus:
        compact_item = compact(item)
        item_words = len(words(item))
        if len(compact_value) >= 40 and abs(len(compact_value) - len(compact_item)) <= max(20, len(compact_value) * 0.25) and compact_value in compact_item:
            return True
        if value_words >= 10 and 0.75 <= value_words / max(1, item_words) <= 1.25 and token_recall(value, item) >= 0.9:
            return True
    return False


def looks_like_prose(block: u.Block, body_size: float, text: str) -> bool:
    value = norm(text)
    tokens = words(value)
    if len(tokens) < 8 or len(value) < 55:
        return False
    if u.CAPTION_RE.match(value) or META_RE.match(value) or AFFILIATION_RE.match(value):
        return False
    if REFERENCE_LINE_RE.match(value) and re.search(r"\b(?:19|20)\d{2}\b", value):
        return False
    alpha = sum(character.isalpha() for character in value)
    digits = sum(character.isdigit() for character in value)
    if alpha / max(1, len(value)) < 0.43 or digits / max(1, len(value)) > 0.22:
        return False
    if FIGURE_LABEL_RE.match(value) and len(tokens) < 35:
        return False
    if not (body_size - 0.72 <= block.median_size <= body_size + 1.05):
        return False
    if not re.search(r"[.!?;:]", value) and len(tokens) < 24:
        return False
    return True


def extended_data_start(manifest: dict[str, Any]) -> int | None:
    pages = [
        int(entry.get("page") or 0)
        for entry in manifest.get("evidence_outline", [])
        if entry.get("kind") == "figure" and norm(entry.get("title")).lower().startswith("extended data")
    ]
    pages = [page for page in pages if page > 0]
    return min(pages) if pages else None


def extract_layout_pages(pdf: Path) -> tuple[fitz.Document, list[list[u.Block]], float]:
    document = fitz.open(pdf)
    raw_pages: list[list[u.Block]] = []
    for page_number, page in enumerate(document, 1):
        raw_pages.append([
            block
            for raw in page.get_text("dict", sort=False).get("blocks", [])
            for block in u.blocks_from_dict(page_number, raw)
        ])
    repeated = u.detect_repeated_headers_footers(document, raw_pages)
    clean_pages: list[list[u.Block]] = []
    for index, blocks in enumerate(raw_pages):
        clean = [block for block in blocks if not u.is_noise(block, document[index].rect, repeated)]
        clean_pages.append(base.ORIGINAL_PAGE_READING_ORDER(clean, document[index].rect))
    return document, clean_pages, u.body_font_size(clean_pages)


def initial_bold_headings(block: u.Block, candidates: list[Heading], body_size: float) -> tuple[list[Heading], str]:
    groups: list[dict[str, Any]] = []
    for span in sorted(block.spans, key=lambda item: (round(item.bbox[1], 1), item.bbox[0])):
        if not groups or abs(groups[-1]["y"] - span.bbox[1]) > 1.2:
            groups.append({"y": span.bbox[1], "spans": [span]})
        else:
            groups[-1]["spans"].append(span)
    bold_lines: list[tuple[str, float]] = []
    for group in groups:
        relevant = [span for span in group["spans"] if not span.superscript and re.search(r"[A-Za-z]", span.text)]
        if not relevant or not all(span.bold for span in relevant) or max(span.size for span in relevant) < body_size + 0.18:
            break
        text = norm("".join(span.text for span in group["spans"]))
        if not text:
            break
        bold_lines.append((text, statistics.median(span.size for span in relevant)))
    if not bold_lines:
        return [], norm(block.text)

    headings: list[Heading] = []
    index = 0
    while index < len(bold_lines):
        remaining = " ".join(text for text, _ in bold_lines[index:])
        matches = [item for item in candidates if remaining.lower().startswith(norm(item.title).lower())]
        if matches:
            selected = max(matches, key=lambda item: len(item.title))
            consumed = 0
            accumulated = ""
            while index + consumed < len(bold_lines) and len(accumulated) < len(norm(selected.title)):
                accumulated = norm(accumulated + " " + bold_lines[index + consumed][0])
                consumed += 1
            headings.append(selected)
            index += consumed
            continue
        text, size = bold_lines[index]
        if len(words(text)) < 2 or len(text) < 4 or len(text) > 150:
            break
        combined = text
        consumed = 1
        while index + consumed < len(bold_lines) and abs(bold_lines[index + consumed][1] - size) < 0.25:
            combined = norm(combined + " " + bold_lines[index + consumed][0])
            consumed += 1
        headings.append(Heading(combined, block.page, 3))
        index += consumed

    if not headings:
        return [], norm(block.text)
    remainder = norm(block.text)
    for heading in headings:
        title = norm(heading.title)
        if remainder.lower().startswith(title.lower()):
            remainder = norm(remainder[len(title):])
        else:
            break
    return headings, remainder
