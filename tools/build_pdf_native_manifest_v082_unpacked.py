#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import collections
import hashlib
import html
import io
import json
import math
import re
import statistics
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import fitz
from PIL import Image

SECTION_EXACT = {
    "summary", "abstract", "introduction", "results", "discussion", "methods", "materials and methods",
    "star methods", "limitations of the study", "resource availability", "lead contact", "materials availability",
    "data and code availability", "experimental model and study participant details", "method details",
    "quantification and statistical analysis", "supplemental information", "supplementary information",
    "acknowledgments", "acknowledgements", "author contributions", "declaration of interests", "references",
    "online content", "reporting summary", "data availability", "code availability", "ethics declarations",
    "extended data", "main", "research article summary", "graphical abstract", "highlights", "in brief",
}
CAPTION_RE = re.compile(
    r"^(?:Graphical abstract\b|(?:(?:Figure|Fig\.|Extended Data Fig\.|Supplementary Fig\.|Supplementary Figure|Table|Extended Data Table|Supplementary Table)\s*[A-Z]?\d+[A-Za-z]?)(?:\s*[.|:]|\s*\|))",
    re.I,
)
REFERENCE_HEADING_RE = re.compile(r"^(?:references(?: and notes)?|bibliography|literature cited)$", re.I)
REF_START_RE = re.compile(r"^(\d{1,3})[\.\s]+(?=[A-Z\[])" )
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
URL_RE = re.compile(r"https?://\S+")
FIG_REF_RE = re.compile(r"\b(?P<label>Figure|Fig\.|Extended Data Fig\.|Supplementary Fig\.|Supplementary Figure|Table|Extended Data Table|Supplementary Table)\s+(?P<num>[A-Z]?\d+[A-Za-z]?)", re.I)
TERMINAL_RE = re.compile(r"[.!?][\"'’”\)\]]?$|[:;]$")


@dataclass
class Span:
    text: str
    bbox: tuple[float, float, float, float]
    size: float
    flags: int
    font: str

    @property
    def bold(self) -> bool:
        return bool(self.flags & 16) or "bold" in self.font.lower()

    @property
    def superscript(self) -> bool:
        return bool(self.flags & 1)


@dataclass
class Block:
    page: int
    bbox: tuple[float, float, float, float]
    lines: list[str]
    spans: list[Span]
    text: str
    median_size: float
    max_size: float
    bold_ratio: float
    column: str = "full"
    kind: str = "other"
    heading_text: str | None = None
    source_sha256: str = ""


@dataclass
class Event:
    kind: str
    page: int
    text: str
    block: Block
    section_id: str | None = None
    citation_ids: list[str] = field(default_factory=list)


def norm(text: str) -> str:
    text = text.replace("\u00ad", "").replace("￾", "")
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def slugify(text: str, default: str = "section") -> str:
    value = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:72] or default


def join_lines(lines: Iterable[str]) -> str:
    out = ""
    for raw in lines:
        line = norm(raw)
        if not line:
            continue
        if out.endswith("-") and re.match(r"^[a-z]", line):
            out = out[:-1] + line
        else:
            out += (" " if out else "") + line
    return norm(out)


def blocks_from_dict(page: int, raw: dict[str, Any]) -> list[Block]:
    if raw.get("type") != 0:
        return []
    line_records: list[dict[str, Any]] = []
    for line in raw.get("lines", []):
        spans: list[Span] = []
        parts: list[str] = []
        for item in line.get("spans", []):
            text = item.get("text", "")
            if not text:
                continue
            parts.append(text)
            spans.append(Span(
                text=text,
                bbox=tuple(float(x) for x in item.get("bbox", (0, 0, 0, 0))),
                size=float(item.get("size", 0)),
                flags=int(item.get("flags", 0)),
                font=str(item.get("font", "")),
            ))
        line_text = "".join(parts)
        if not line_text.strip() or not spans:
            continue
        line_records.append({
            "text": line_text,
            "spans": spans,
            "x0": min(x.bbox[0] for x in spans),
            "y0": min(x.bbox[1] for x in spans),
            "x1": max(x.bbox[2] for x in spans),
            "y1": max(x.bbox[3] for x in spans),
        })
    if not line_records:
        return []
    baseline_x = min(x["x0"] for x in line_records)
    heights = [x["y1"] - x["y0"] for x in line_records]
    median_height = statistics.median(heights) if heights else 10.0
    groups: list[list[dict[str, Any]]] = [[]]
    for idx, record in enumerate(line_records):
        split = False
        if idx > 0:
            prev = line_records[idx - 1]
            gap = record["y0"] - prev["y1"]
            indented = record["x0"] - baseline_x >= max(7.0, median_height * 0.65)
            previous_sentence_closed = bool(re.search(r"[.!?][\"'’”\)\]]?$", norm(prev["text"])))
            starts_new_sentence = bool(re.match(r"^[A-Z0-9]", norm(record["text"])))
            # Nature-family PDFs encode a new paragraph primarily through first-line indentation,
            # while Cell commonly uses a slightly larger vertical gap. Both signals are retained.
            if (indented and previous_sentence_closed and starts_new_sentence) or gap > max(3.5, median_height * 0.42):
                split = True
        if split and groups[-1]:
            groups.append([])
        groups[-1].append(record)

    output: list[Block] = []
    raw_bbox = tuple(float(x) for x in raw.get("bbox", (0, 0, 0, 0)))
    for group in groups:
        spans = [span for line in group for span in line["spans"]]
        lines = [line["text"] for line in group]
        text = join_lines(lines)
        if not text:
            continue
        sizes = [x.size for x in spans if 4 <= x.size <= 30]
        median_size = statistics.median(sizes) if sizes else 0.0
        max_size = max(sizes) if sizes else 0.0
        weighted = sum(max(1, len(x.text)) for x in spans)
        bold_ratio = sum(max(1, len(x.text)) for x in spans if x.bold) / weighted if weighted else 0.0
        bbox = (
            min(line["x0"] for line in group), min(line["y0"] for line in group),
            max(line["x1"] for line in group), max(line["y1"] for line in group),
        ) if group else raw_bbox
        output.append(Block(page=page, bbox=bbox, lines=lines, spans=spans, text=text,
                            median_size=median_size, max_size=max_size, bold_ratio=bold_ratio,
                            source_sha256=digest(text)))
    return output


def block_from_dict(page: int, raw: dict[str, Any]) -> Block | None:
    blocks = blocks_from_dict(page, raw)
    return blocks[0] if blocks else None


def repeat_key(text: str) -> str:
    text = norm(text).lower()
    text = re.sub(r"\b\d+\b", "#", text)
    text = DOI_RE.sub("doi", text)
    return text


def detect_repeated_headers_footers(doc: fitz.Document, pages: list[list[Block]]) -> set[str]:
    counts: collections.Counter[str] = collections.Counter()
    for i, blocks in enumerate(pages):
        h = doc[i].rect.height
        for b in blocks:
            if b.bbox[1] < h * 0.09 or b.bbox[3] > h * 0.91:
                key = repeat_key(b.text)
                if 2 <= len(key) <= 220:
                    counts[key] += 1
    threshold = max(3, math.ceil(len(doc) * 0.12))
    return {k for k, v in counts.items() if v >= threshold}


def is_noise(block: Block, page_rect: fitz.Rect, repeated: set[str]) -> bool:
    text = norm(block.text)
    low = text.lower()
    top_bottom = block.bbox[1] < page_rect.height * 0.075 or block.bbox[3] > page_rect.height * 0.93
    if top_bottom and repeat_key(text) in repeated:
        return True
    if re.fullmatch(r"\d{1,4}", text) and top_bottom:
        return True
    if low in {"article", "research article", "open access", "check for updates", "nature", "cell", "science"} and (top_bottom or block.bbox[1] < page_rect.height * 0.15):
        return True
    if low.startswith("downloaded from ") and block.bbox[3] > page_rect.height * 0.86:
        return True
    if re.match(r"^(nature(?: genetics| medicine| communications| machine intelligence)?|cell|science)\s*(?:\||volume|vol)", low) and top_bottom:
        return True
    return False


def assign_columns(blocks: list[Block], width: float) -> None:
    for b in blocks:
        x0, _, x1, _ = b.bbox
        span = x1 - x0
        center = (x0 + x1) / 2
        if span > width * 0.62 or (x0 < width * 0.27 and x1 > width * 0.73):
            b.column = "full"
        elif center < width * 0.5:
            b.column = "left"
        else:
            b.column = "right"


def page_reading_order(blocks: list[Block], rect: fitz.Rect) -> list[Block]:
    assign_columns(blocks, rect.width)
    full = sorted([b for b in blocks if b.column == "full"], key=lambda x: (x.bbox[1], x.bbox[0]))
    columns = [b for b in blocks if b.column != "full"]
    bounds = [0.0] + [b.bbox[1] for b in full] + [rect.height + 1]
    ordered: list[Block] = []
    for idx in range(len(bounds) - 1):
        lo, hi = bounds[idx], bounds[idx + 1]
        band = [b for b in columns if lo <= (b.bbox[1] + b.bbox[3]) / 2 < hi]
        ordered.extend(sorted([b for b in band if b.column == "left"], key=lambda x: (x.bbox[1], x.bbox[0])))
        ordered.extend(sorted([b for b in band if b.column == "right"], key=lambda x: (x.bbox[1], x.bbox[0])))
        if idx < len(full):
            ordered.append(full[idx])
    # Fallback for any block excluded by a boundary edge case.
    seen = {id(b) for b in ordered}
    ordered.extend(sorted([b for b in blocks if id(b) not in seen], key=lambda x: (x.bbox[1], x.bbox[0])))
    return ordered


def body_font_size(pages: list[list[Block]]) -> float:
    # Body paragraphs are long and normally use a stable type size. Captions and
    # figure-panel labels are deliberately excluded because they are smaller and
    # otherwise make almost every plot label look like a section heading.
    sizes: list[float] = []
    for blocks in pages:
        for b in blocks:
            if len(b.text) < 140 or CAPTION_RE.match(b.text):
                continue
            if 7.0 <= b.median_size <= 12.5:
                sizes.append(b.median_size)
    return statistics.median(sizes) if sizes else 8.5


def split_heading_prefix(block: Block, body_size: float) -> list[Block]:
    if len(block.lines) < 2 or not block.spans or CAPTION_RE.match(block.text):
        return [block]
    first_line = norm(block.lines[0])
    if not first_line or len(first_line) > 180:
        return [block]
    first_spans = [s for s in block.spans if abs(s.bbox[1] - block.spans[0].bbox[1]) < max(2.5, s.size * 0.5)]
    first_size = max((s.size for s in first_spans), default=0)
    first_bold = any(s.bold for s in first_spans)
    rest = join_lines(block.lines[1:])
    exact = first_line.lower().strip(" :") in SECTION_EXACT or bool(REFERENCE_HEADING_RE.fullmatch(first_line))
    typographic = first_size >= body_size + 1.2 and len(first_line.split()) >= 2
    if rest and (exact or typographic) and not TERMINAL_RE.search(first_line):
        h = Block(page=block.page, bbox=block.bbox, lines=[first_line], spans=first_spans, text=first_line,
                  median_size=first_size, max_size=first_size, bold_ratio=1.0 if first_bold else 0.0,
                  column=block.column, kind="heading", heading_text=first_line, source_sha256=digest(first_line))
        remaining_spans = [s for s in block.spans if s not in first_spans]
        sizes = [s.size for s in remaining_spans] or [body_size]
        r = Block(page=block.page, bbox=block.bbox, lines=block.lines[1:], spans=remaining_spans, text=rest,
                  median_size=statistics.median(sizes), max_size=max(sizes), bold_ratio=0.0,
                  column=block.column, kind="body", source_sha256=digest(rest))
        return [h, r]
    return [block]


def classify(block: Block, body_size: float, in_references: bool) -> str:
    text = norm(block.text)
    low = text.lower().strip(" :")
    if REFERENCE_HEADING_RE.fullmatch(low):
        return "heading"
    if CAPTION_RE.match(text):
        return "caption"
    if in_references:
        return "reference"
    if low in SECTION_EXACT:
        return "heading"
    words = text.split()
    numeric_fraction = sum(ch.isdigit() for ch in text) / max(1, len(text))
    heading_shape = (
        8 <= len(text) <= 180
        and 2 <= len(words) <= 18
        and not text.startswith(("•", "·"))
        and not TERMINAL_RE.search(text)
        and numeric_fraction < 0.22
        and "=" not in text
        and not DOI_RE.search(text)
        and not URL_RE.search(text)
    )
    typographic = block.max_size >= body_size + 1.15 or (block.bold_ratio >= 0.72 and block.median_size >= body_size - 0.15 and len(text) >= 18)
    if heading_shape and typographic:
        return "heading"
    if len(text) >= 20:
        return "body"
    return "other"


def numeric_citations(block: Block) -> list[str]:
    ids: list[str] = []
    for span in block.spans:
        token = norm(span.text)
        if not span.superscript:
            continue
        for part in re.split(r"[,;\s]+", token):
            m = re.fullmatch(r"(\d{1,3})(?:[–-](\d{1,3}))?", part)
            if not m:
                continue
            a = int(m.group(1)); b = int(m.group(2) or a)
            if 1 <= a <= 999 and a <= b <= 999 and b - a <= 30:
                for value in range(a, b + 1):
                    s = str(value)
                    if s not in ids:
                        ids.append(s)
    return ids


def should_merge(prev: Event, curr: Event) -> bool:
    if prev.kind != "body" or curr.kind != "body" or prev.section_id != curr.section_id:
        return False
    if curr.page - prev.page > 1:
        return False
    if curr.page == prev.page and prev.block.column != curr.block.column:
        return False
    if len(prev.text) > 2000:
        return False
    if prev.text.endswith("-"):
        return True
    if TERMINAL_RE.search(prev.text):
        return False
    if re.match(r"^[a-zα-ω]", curr.text):
        return True
    return len(prev.text) < 120


def merge_events(prev: Event, curr: Event) -> Event:
    left, right = prev.text.rstrip(), curr.text.lstrip()
    text = norm(left[:-1] + right) if left.endswith("-") and re.match(r"^[a-z]", right) else norm(left + " " + right)
    citations = list(dict.fromkeys(prev.citation_ids + curr.citation_ids))
    spans = prev.block.spans + curr.block.spans
    block = Block(page=prev.page, bbox=prev.block.bbox, lines=[text], spans=spans, text=text,
                  median_size=prev.block.median_size, max_size=max(prev.block.max_size, curr.block.max_size),
                  bold_ratio=prev.block.bold_ratio, column=prev.block.column, kind="body", source_sha256=digest(text))
    return Event(kind="body", page=prev.page, text=text, block=block, section_id=prev.section_id, citation_ids=citations)


def parse_authors(first_pages_text: str, title: str) -> list[str]:
    text = first_pages_text
    idx = text.lower().find(title.lower()[:50])
    tail = text[idx + len(title):] if idx >= 0 else text
    tail = re.split(r"\b(?:SUMMARY|ABSTRACT|INTRODUCTION|Received:|https?://doi\.org/)\b", tail, maxsplit=1, flags=re.I)[0]
    lines = [norm(x) for x in tail.splitlines() if norm(x)]
    candidates = []
    for line in lines[:20]:
        if len(line) > 700 or re.search(r"Department|University|Institute|Hospital|Correspondence|Authors|Article", line, re.I):
            continue
        if line.count(",") >= 2 or " and " in line or " & " in line:
            candidates.append(line)
    if not candidates:
        return ["Authors listed in the source PDF"]
    raw = max(candidates, key=len)
    raw = re.sub(r"\d+(?:,\d+)*\*?", "", raw)
    raw = re.sub(r"\s+", " ", raw)
    parts = re.split(r",\s+|\s+and\s+|\s*&\s*", raw)
    clean = [p.strip(" ,*✉") for p in parts if 2 <= len(p.strip()) <= 80]
    return clean[:80] or [raw[:300]]


def translate_section_fallback(title: str) -> str:
    mapping = {
        "summary": "摘要", "abstract": "摘要", "introduction": "引言", "results": "结果", "discussion": "讨论",
        "methods": "方法", "star methods": "STAR方法", "references": "参考文献", "acknowledgments": "致谢",
        "acknowledgements": "致谢", "author contributions": "作者贡献", "declaration of interests": "利益声明",
        "limitations of the study": "研究局限", "supplemental information": "补充信息", "supplementary information": "补充信息",
        "data availability": "数据可用性", "code availability": "代码可用性", "resource availability": "资源可用性",
        "graphical abstract": "图形摘要", "highlights": "要点", "in brief": "简述",
    }
    return mapping.get(title.lower(), title)


def asset_id_from_caption(text: str, existing: set[str]) -> str:
    """Return the logical source asset ID.

    Publishers often repeat the same caption identifier on a continuation page
    (for example ``Extended Data Fig. 3`` followed by the complete legend on
    the next page). Those are one source figure, not two reader assets. Known
    figure/table identifiers therefore remain stable; only genuinely unlabelled
    assets receive a numeric disambiguator.
    """
    m = re.match(r"^(Figure|Fig\.|Extended Data Fig\.|Supplementary Fig\.|Supplementary Figure|Table|Extended Data Table|Supplementary Table)\s*([A-Z]?\d+[A-Za-z]?)", text, re.I)
    if m:
        label = m.group(1).lower().replace(".", "")
        label = label.replace("supplementary figure", "supplementary-figure").replace("supplementary fig", "supplementary-figure")
        label = label.replace("extended data figure", "extended-data-figure").replace("extended data fig", "extended-data-figure")
        label = label.replace("extended data table", "extended-data-table").replace(" ", "-")
        if label == "fig":
            label = "figure"
        return f"{label}-{m.group(2).lower()}"
    if text.lower().startswith("graphical abstract"):
        return "graphical-abstract"
    base = "asset"
    value = base
    i = 2
    while value in existing:
        value = f"{base}-{i}"
        i += 1
    return value


def caption_quality(text: str) -> tuple[int, int]:
    low = text.lower()
    placeholder = int("see next page for caption" in low or "legend continued" in low)
    return (-placeholder, len(text))


def render_crop(doc: fitz.Document, block: Block, previous_caption_y: dict[int, float], scale: float = 1.6) -> tuple[str, dict[str, Any]]:
    page_index = block.page - 1
    page = doc[page_index]
    rect = page.rect
    y_caption = block.bbox[1]
    source_page = page_index
    if y_caption < rect.height * 0.30 and page_index > 0:
        page = doc[page_index - 1]
        rect = page.rect
        source_page = page_index - 1
        clip = fitz.Rect(rect.width * 0.03, rect.height * 0.05, rect.width * 0.97, rect.height * 0.92)
    else:
        top = max(rect.height * 0.055, previous_caption_y.get(page_index, rect.height * 0.055))
        bottom = min(rect.height * 0.92, max(top + rect.height * 0.22, y_caption - 4))
        if bottom - top < rect.height * 0.2:
            top = rect.height * 0.055
        clip = fitz.Rect(rect.width * 0.025, top, rect.width * 0.975, bottom)
        previous_caption_y[page_index] = min(rect.height * 0.90, block.bbox[3] + 8)
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=92, method=6)
    data = out.getvalue()
    uri = "data:image/webp;base64," + base64.b64encode(data).decode("ascii")
    return uri, {
        "source_page": source_page + 1,
        "clip": [round(clip.x0, 2), round(clip.y0, 2), round(clip.x1, 2), round(clip.y1, 2)],
        "pixels": [img.width, img.height],
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def build_inline(text: str, citations: list[str], asset_ids: set[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    pos = 0
    for m in FIG_REF_RE.finditer(text):
        if m.start() > pos:
            items.append({"text": text[pos:m.start()]})
        label = m.group("label").lower().replace(".", "")
        label = label.replace("supplementary figure", "supplementary-figure").replace("supplementary fig", "supplementary-figure")
        label = label.replace("extended data figure", "extended-data-figure").replace("extended data fig", "extended-data-figure")
        label = label.replace("extended data table", "extended-data-table").replace(" ", "-")
        if label == "fig": label = "figure"
        aid = f"{label}-{m.group('num').lower()}"
        item: dict[str, Any] = {"text": m.group(0)}
        if aid in asset_ids:
            item["figure_ids"] = [aid]
        items.append(item)
        pos = m.end()
    if pos < len(text):
        items.append({"text": text[pos:]})
    if not items:
        items = [{"text": text}]
    if citations:
        items[-1]["citation_ids"] = citations
    return items


def reference_item(number: int, text: str) -> dict[str, Any]:
    doi_match = DOI_RE.search(text)
    url_match = URL_RE.search(text)
    url = None
    if doi_match:
        url = "https://doi.org/" + doi_match.group(0).rstrip(".,;)")
    elif url_match:
        url = url_match.group(0).rstrip(".,;)")
    item: dict[str, Any] = {"id": str(number), "text": norm(text)}
    if url:
        item["url"] = url
    return item


def pdf_reference_candidates(doc: fitz.Document) -> dict[int, str]:
    pattern = re.compile(r"(?<!\d)(\d{1,3})\.\s+(?=[A-Z\[])")
    candidates: dict[int, list[str]] = collections.defaultdict(list)
    for page in doc:
        text = page.get_text("text", sort=True)
        matches = [m for m in pattern.finditer(text) if 1 <= int(m.group(1)) <= 300]
        unique = sorted({int(m.group(1)) for m in matches})
        if len(unique) < 10:
            continue
        # Reference pages contain a long near-contiguous numeric run. This excludes numbered
        # method lists and figure-axis labels without relying on a publisher-specific heading.
        longest = 1
        current = 1
        for a, b in zip(unique, unique[1:]):
            if b == a + 1:
                current += 1
                longest = max(longest, current)
            else:
                current = 1
        if longest < 8:
            continue
        for idx, match in enumerate(matches):
            number = int(match.group(1))
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            segment = norm(text[match.end():end])
            if not (25 <= len(segment) <= 1800):
                continue
            # Bibliographic entries almost always contain a publication year, DOI, PMID, or
            # recognizable volume/page punctuation. False positive in-text numbers usually do not.
            bibliographic = bool(re.search(r"\((?:19|20)\d{2}\)", segment) or DOI_RE.search(segment) or re.search(r"\b(?:doi|pmid):", segment, re.I))
            if bibliographic:
                candidates[number].append(segment)
    selected: dict[int, str] = {}
    for number, values in candidates.items():
        # Prefer the candidate with a year and the greatest information content.
        values = sorted(values, key=lambda x: (bool(re.search(r"\((?:19|20)\d{2}\)", x)), len(x)), reverse=True)
        selected[number] = values[0]
    if not selected:
        return {}
    # Retain the largest contiguous prefix or near-contiguous numeric range.
    maximum = max(selected)
    if 1 in selected:
        cutoff = 1
        misses = 0
        for number in range(1, maximum + 1):
            if number in selected:
                cutoff = number
            else:
                misses += 1
                if misses > max(3, int(cutoff * 0.12)):
                    break
        return {n: selected[n] for n in sorted(selected) if n <= cutoff}
    return selected


def parse_references(events: list[Event], doc: fitz.Document | None = None) -> list[dict[str, Any]]:
    chunks = [norm(e.text) for e in events if e.kind == "reference" and norm(e.text)]
    joined = " ".join(chunks)
    starts = list(re.finditer(r"(?<!\d)(\d{1,3})[.\t]\s*(?=[A-Z\[])" , joined))
    refs: dict[int, str] = {}
    if starts:
        for idx, match in enumerate(starts):
            end = starts[idx + 1].start() if idx + 1 < len(starts) else len(joined)
            number = int(match.group(1))
            text = norm(joined[match.end():end])
            if text and (number not in refs or len(text) > len(refs[number])):
                refs[number] = text
    elif chunks:
        refs = {i: chunk for i, chunk in enumerate(chunks, 1) if len(chunk) > 25}
    if doc is not None:
        for number, text in pdf_reference_candidates(doc).items():
            if number not in refs or len(text) > len(refs[number]):
                refs[number] = text
    output = []
    for output_id, number in enumerate(sorted(refs), 1):
        text = refs[number]
        item = reference_item(output_id, text)
        output.append(item)
    return output


def caption_title(text: str) -> str:
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    return first[:240]


def build_manifest(pdf: Path, source: dict[str, Any], audit_path: Path | None = None) -> dict[str, Any]:
    doc = fitz.open(pdf)
    raw_pages: list[list[Block]] = []
    for page_no, page in enumerate(doc, 1):
        blocks = [b for raw in page.get_text("dict", sort=False).get("blocks", []) for b in blocks_from_dict(page_no, raw)]
        raw_pages.append(blocks)
    repeated = detect_repeated_headers_footers(doc, raw_pages)
    clean_pages: list[list[Block]] = []
    for idx, blocks in enumerate(raw_pages):
        clean = [b for b in blocks if not is_noise(b, doc[idx].rect, repeated)]
        clean_pages.append(page_reading_order(clean, doc[idx].rect))
    body_size = body_font_size(clean_pages)

    expanded_pages: list[list[Block]] = []
    for blocks in clean_pages:
        expanded: list[Block] = []
        for b in blocks:
            expanded.extend(split_heading_prefix(b, body_size))
        expanded_pages.append(expanded)

    events: list[Event] = []
    current_section = "front-matter"
    section_titles: list[tuple[str, str, int]] = [(current_section, "Front matter", 1)]
    section_ids = {current_section}
    in_refs = False
    for page_blocks in expanded_pages:
        for original_block in page_blocks:
            original_low = norm(original_block.text).lower().strip(" :")
            if in_refs and ((original_low in SECTION_EXACT and not REFERENCE_HEADING_RE.fullmatch(original_low)) or CAPTION_RE.match(original_block.text)):
                in_refs = False
            inline_match = re.search(r"\bReferences(?: and notes)?\s+(?=\d{1,3}\.)", original_block.text, re.I)
            ref_starts = list(re.finditer(r"(?<!\d)(\d{1,3})[.\t]\s*(?=[A-Z\[])", original_block.text))
            implicit_reference_block = len(ref_starts) >= 4 and max(int(x.group(1)) for x in ref_starts) >= 10
            candidate_blocks: list[Block] = []
            if inline_match:
                before = norm(original_block.text[:inline_match.start()])
                after = norm(original_block.text[inline_match.end():])
                if before:
                    candidate_blocks.append(Block(page=original_block.page, bbox=original_block.bbox, lines=[before], spans=original_block.spans, text=before, median_size=original_block.median_size, max_size=original_block.max_size, bold_ratio=original_block.bold_ratio, column=original_block.column, kind="body", source_sha256=digest(before)))
                candidate_blocks.append(Block(page=original_block.page, bbox=original_block.bbox, lines=["References"], spans=original_block.spans, text="References", median_size=original_block.median_size, max_size=original_block.max_size, bold_ratio=1.0, column=original_block.column, kind="heading", heading_text="References", source_sha256=digest("References")))
                if after:
                    candidate_blocks.append(Block(page=original_block.page, bbox=original_block.bbox, lines=[after], spans=original_block.spans, text=after, median_size=original_block.median_size, max_size=original_block.max_size, bold_ratio=original_block.bold_ratio, column=original_block.column, kind="reference", source_sha256=digest(after)))
            elif implicit_reference_block:
                first = ref_starts[0].start()
                before = norm(original_block.text[:first])
                after = norm(original_block.text[first:])
                if before:
                    candidate_blocks.append(Block(page=original_block.page, bbox=original_block.bbox, lines=[before], spans=original_block.spans, text=before, median_size=original_block.median_size, max_size=original_block.max_size, bold_ratio=original_block.bold_ratio, column=original_block.column, kind="body", source_sha256=digest(before)))
                candidate_blocks.append(Block(page=original_block.page, bbox=original_block.bbox, lines=["References"], spans=original_block.spans, text="References", median_size=original_block.median_size, max_size=original_block.max_size, bold_ratio=1.0, column=original_block.column, kind="heading", heading_text="References", source_sha256=digest("References")))
                candidate_blocks.append(Block(page=original_block.page, bbox=original_block.bbox, lines=[after], spans=original_block.spans, text=after, median_size=original_block.median_size, max_size=original_block.max_size, bold_ratio=original_block.bold_ratio, column=original_block.column, kind="reference", source_sha256=digest(after)))
            else:
                candidate_blocks = [original_block]
            for block in candidate_blocks:
                kind = block.kind if block.kind in {"heading", "body", "reference"} else classify(block, body_size, in_refs)
                block.kind = kind
                text = norm(block.text)
                if not text:
                    continue
                if in_refs and kind == "caption":
                    in_refs = False
                    current_section = "extended-data"
                    if current_section not in section_ids:
                        section_ids.add(current_section)
                        section_titles.append((current_section, "Extended Data", block.page))
                if kind == "heading":
                    if REFERENCE_HEADING_RE.fullmatch(text):
                        in_refs = True
                    base = slugify(text)
                    sid = base
                    n = 2
                    while sid in section_ids:
                        sid = f"{base}-{n}"; n += 1
                    section_ids.add(sid)
                    current_section = sid
                    section_titles.append((sid, text, block.page))
                    events.append(Event("heading", block.page, text, block, section_id=sid))
                elif kind == "reference":
                    events.append(Event("reference", block.page, text, block, section_id="references"))
                elif kind == "caption":
                    events.append(Event("caption", block.page, text, block, section_id=current_section))
                else:
                    event = Event("body", block.page, text, block, section_id=current_section, citation_ids=numeric_citations(block))
                    if events and should_merge(events[-1], event):
                        events[-1] = merge_events(events[-1], event)
                    else:
                        events.append(event)

    # Merge caption continuations: a caption event absorbs short immediately following body blocks on the same/next page
    # until a terminal sentence and a clear new paragraph/heading boundary are reached.
    merged_events: list[Event] = []
    i = 0
    while i < len(events):
        e = events[i]
        if e.kind == "caption":
            parts = [e.text]
            j = i + 1
            while j < len(events):
                nxt = events[j]
                if nxt.kind != "body" or nxt.page - e.page > 1 or nxt.section_id != e.section_id:
                    break
                if len(nxt.text) > 900 and TERMINAL_RE.search(parts[-1]):
                    break
                if re.match(r"^(?:The|We|To|In|Our|Next|Together|These|This)\b", nxt.text) and TERMINAL_RE.search(parts[-1]):
                    break
                parts.append(nxt.text)
                j += 1
                if len(" ".join(parts)) > 3500:
                    break
            e.text = norm(" ".join(parts))
            e.block.text = e.text
            merged_events.append(e)
            i = j
        else:
            merged_events.append(e)
            i += 1
    events = merged_events

    first_text = "\n".join(doc[i].get_text("text") for i in range(min(2, len(doc))))
    authors = parse_authors(first_text, source["title"])
    correspondence = ""
    emails = sorted(set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", first_text)))
    if emails:
        correspondence = ", ".join(emails)

    references = parse_references(events, doc)
    ref_max = len(references)
    assets: list[dict[str, Any]] = []
    asset_audit: list[dict[str, Any]] = []
    asset_ids: set[str] = set()
    asset_index: dict[str, int] = {}
    previous_caption_y: dict[int, float] = {}
    for e in events:
        if e.kind != "caption":
            continue
        aid = asset_id_from_caption(e.text, asset_ids)
        image_src, render_info = render_crop(doc, e.block, previous_caption_y)
        title = caption_title(e.text)
        panels = []
        panel_matches = list(re.finditer(r"\(([A-Za-z0-9]+)\)\s*", e.text))
        for idx, match in enumerate(panel_matches):
            end = panel_matches[idx + 1].start() if idx + 1 < len(panel_matches) else len(e.text)
            explanation = norm(e.text[match.end():end])
            if explanation:
                panels.append({"label": match.group(1), "title": explanation[:120], "explanation": explanation})
        candidate = {
            "id": aid,
            # Tables are retained as lossless source images. This avoids silently
            # corrupting complex merged cells while preserving the standard card,
            # right viewer, zoom and figure-study interactions.
            "kind": "figure",
            "group": e.section_id or "main",
            "title_en": title,
            "title_zh": title,
            "intro": e.text[:360],
            "image_src": image_src,
            "source_page": render_info["source_page"],
            "image_format": "webp",
            "hires": True,
            "source_render": "pdf-caption-guided-region",
            "caption_en": e.text,
            "caption_zh": e.text,
            "study": {
                "overview": e.text,
                "panels": panels,
                "conclusion": e.text,
                "boundary": "Panel explanations are restricted to information explicitly stated in the source caption; no unsupported interpretation is added."
            }
        }
        audit_candidate = {"id": aid, "caption_sha256": digest(e.text), **render_info}
        if aid not in asset_index:
            asset_index[aid] = len(assets)
            asset_ids.add(aid)
            assets.append(candidate)
            asset_audit.append(audit_candidate)
            # Place the logical asset once, at its first appearance in reading order.
            e.block.heading_text = aid
        else:
            index = asset_index[aid]
            if caption_quality(e.text) > caption_quality(assets[index]["caption_en"]):
                assets[index] = candidate
                asset_audit[index] = audit_candidate
            # Continuation legends must not create a duplicate card in the article.
            e.block.heading_text = None

    sections_by_id: dict[str, dict[str, Any]] = {}
    ordered_sections: list[dict[str, Any]] = []
    for sid, title, page in section_titles:
        if sid == "references":
            continue
        section = {"id": sid, "title_en": title, "title_zh": translate_section_fallback(title), "level": 2, "blocks": []}
        sections_by_id[sid] = section
        ordered_sections.append(section)

    paragraph_index = 0
    event_chars = collections.Counter()
    for e in events:
        event_chars[e.kind] += len(e.text)
        if e.kind == "body":
            if e.section_id == "references" or e.section_id not in sections_by_id:
                continue
            paragraph_index += 1
            pid = f"p-{paragraph_index:04d}"
            cites = [c for c in e.citation_ids if not ref_max or int(c) <= ref_max]
            block = {
                "type": "paragraph",
                "id": pid,
                "source_pages": str(e.page),
                "english": [{"text": e.text, **({"citation_ids": cites} if cites else {})}],
                "chinese": [{"text": e.text, **({"citation_ids": cites} if cites else {})}],
                "source_fragments": [e.text],
            }
            sections_by_id[e.section_id]["blocks"].append(block)
        elif e.kind == "caption" and e.section_id in sections_by_id and e.block.heading_text:
            sections_by_id[e.section_id]["blocks"].append({"type": "asset", "asset_id": e.block.heading_text})

    # Remove empty sections; never remove their text because body events were assigned to a valid section.
    ordered_sections = [s for s in ordered_sections if s["blocks"]]
    if not ordered_sections:
        raise RuntimeError("no content sections extracted")

    # Once asset IDs are known, add interactive figure/table references to English blocks.
    for section in ordered_sections:
        for block in section["blocks"]:
            if block["type"] != "paragraph":
                continue
            text = block["english"][0]["text"]
            citations = block["english"][0].get("citation_ids", [])
            block["english"] = build_inline(text, citations, asset_ids)

    summary_section = next((s for s in ordered_sections if s["title_en"].lower() in {"summary", "abstract"}), ordered_sections[0])
    summary_texts = [b["source_fragments"][0] for b in summary_section["blocks"] if b["type"] == "paragraph"]
    abstract = norm(" ".join(summary_texts))[:5000]
    sentences = re.split(r"(?<=[.!?])\s+", abstract)
    sentences = [s for s in sentences if len(s) > 25]
    first = sentences[0] if sentences else source["title"]
    last = sentences[-1] if sentences else first
    method_section = next((s for s in ordered_sections if "method" in s["title_en"].lower()), None)
    method_text = ""
    if method_section:
        method_text = " ".join(b["source_fragments"][0] for b in method_section["blocks"] if b["type"] == "paragraph")[:1200]
    qa_answers = [
        first,
        f"The source PDF contains {len(doc)} pages, {paragraph_index} extracted natural text blocks, {len(assets)} figure or table assets and {len(references)} references.",
        method_text or "The study design and analytical workflow are described in the Methods sections and figure captions reproduced below.",
        " ".join(sentences[1:3]) if len(sentences) > 2 else last,
        " ".join(sentences[-3:-1]) if len(sentences) > 3 else last,
        "Interpretation is limited to claims and evidence explicitly present in the source PDF; figure-study text is caption-grounded.",
    ]
    questions = [
        "研究解决什么问题？", "核心数据是什么？", "模型或分析的输入与输出是什么？",
        "主要生物学发现是什么？", "主要临床结果是什么？", "最重要的限制是什么？",
    ]
    overview = {
        "qa": [{"question": q, "answer": a} for q, a in zip(questions, qa_answers)],
        "method_heading": "方法流程概括",
        "method": method_text or abstract[:1200] or source["title"],
        "story_label": "整体结论",
        "story": last,
        "scope_note": "本阅读器以源 PDF 为唯一内容依据；英文、图注、参考文献和图像均保留来源页码与完整性审计。"
    }

    manifest = {
        "schema_version": "0.8.2",
        "paper": {
            "key": source["doi"].lower(),
            "title_en": source["title"],
            "title_zh": source["title"],
            "authors": authors,
            "affiliations": [],
            "journal": source["journal"],
            "publisher": "",
            "year": int(source["year"]),
            "doi": source["doi"],
            "pages": len(doc),
            "article_type": "Article",
            "publication_timeline": str(source["year"]),
            "citation": f"Source PDF, {len(doc)} pages",
            "correspondence": correspondence,
            "article_url": f"https://doi.org/{source['doi']}",
            "metadata": [
                {"label": "Source PDF SHA256", "value": hashlib.sha256(pdf.read_bytes()).hexdigest()},
                {"label": "Extraction", "value": "PDF-native, layout-aware, source-audited"}
            ]
        },
        "overview": overview,
        "sections": ordered_sections,
        "assets": assets,
        "terms": [],
        "references": references,
    }

    kept_blocks = [b for page in clean_pages for b in page]
    audit = {
        "schema_version": "v082-pdf-native-audit-1",
        "paper_key": source["key"],
        "source_pdf": str(pdf),
        "source_pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "pages": len(doc),
        "body_font_size": round(body_size, 3),
        "raw_text_blocks": sum(len(x) for x in raw_pages),
        "kept_text_blocks": len(kept_blocks),
        "repeated_header_footer_patterns": len(repeated),
        "events": dict(event_chars),
        "paragraphs": paragraph_index,
        "sections": len(ordered_sections),
        "assets": len(assets),
        "references": len(references),
        "asset_audit": asset_audit,
        "kept_text_sha256": digest("\n".join(b.text for b in kept_blocks)),
        "manifest_source_fragments_sha256": digest("\n".join(
            b["source_fragments"][0] for s in ordered_sections for b in s["blocks"] if b["type"] == "paragraph"
        )),
        "coverage_policy": "Every non-noise PDF text block is classified as heading, body, caption, reference or other; body/caption/reference content is retained in the manifest or audit.",
        "passed": paragraph_index >= max(10, len(doc) // 2) and len(assets) >= 1,
    }
    if audit_path:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description="Build a full PDF-native V0.8.2 CANVAS content manifest")
    p.add_argument("pdf", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--registry", type=Path, required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--audit", type=Path)
    args = p.parse_args()
    registry = json.loads(args.registry.read_text("utf-8"))
    source = next(x for x in registry["papers"] if x["key"] == args.key)
    manifest = build_manifest(args.pdf, source, args.audit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({
        "key": args.key,
        "sections": len(manifest["sections"]),
        "paragraphs": sum(sum(b["type"] == "paragraph" for b in s["blocks"]) for s in manifest["sections"]),
        "assets": len(manifest["assets"]),
        "references": len(manifest["references"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
