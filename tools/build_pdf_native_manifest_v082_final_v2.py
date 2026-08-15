#!/usr/bin/env python3
from __future__ import annotations

"""V0.8.2 strict PDF parser hotfix layer.

Keeps the established final parser architecture, while fixing three source-retention
failures found in sequential 11-paper regression: two-column caption crop anchors,
Nature/Science bibliography reconstruction, and false-positive math detection. It
also raises source-figure rasterization to 3x and enforces exact reference sequences.
"""

import argparse
import json
import re
import statistics
from pathlib import Path
from typing import Any

import fitz

import build_pdf_native_manifest_v082_final as final

base = final.base
ORIGINAL_RENDER_CROP = base.render_crop


def is_formula_block(block: base.Block) -> bool:
    text = base.norm(block.text)
    if not text or len(text) > 420 or final.PANEL_ONLY_RE.fullmatch(text):
        return False
    if base.CAPTION_RE.match(text) or base.DOI_RE.search(text) or base.URL_RE.search(text):
        return False
    low = text.lower().strip(" :")
    if low in base.SECTION_EXACT or base.REFERENCE_HEADING_RE.fullmatch(low):
        return False
    math_font_chars = sum(len(span.text) for span in block.spans if final.MATH_FONT_RE.search(span.font))
    superscript_chars = sum(len(span.text) for span in block.spans if span.superscript)
    math_symbols = sum(ch in "=≈≃≠≤≥<>±×÷∑∫√→←↔∝∞^_{}[]()⊤" for ch in text)
    word_count = len(re.findall(r"[A-Za-z]{2,}", text))
    equation_number = bool(re.search(r"\(\d{1,3}\)\s*$", text))
    strong_operator = bool(re.search(r"(?:=|∑|∫|√|≈|≃|≠|≤|≥|→|←|↔|∝)", text))
    if not re.search(r"[A-Za-zΑ-Ωα-ω0-9]", text):
        return False
    stat_annotation = bool(
        re.search(r"\b(?:P|p)\s*(?:=|<|>|≤|≥)\s*", text)
        or re.search(r"\bHR\s*:", text, re.I)
        or re.search(r"\bn\s*=\s*\d", text, re.I)
        or re.search(r"\bTPS\b", text)
        or re.search(r"\bPD-L1\b", text, re.I)
        or re.search(r"^r\s*=\s*[-−+]?\d", text, re.I)
        or re.search(r"\bvirtual\s+CODEX\b", text, re.I)
        or ("%" in text and re.search(r"(?:≤|≥|<|>)", text))
    )
    if stat_annotation and not equation_number:
        return False
    if len(text) <= 140 and word_count <= 4 and math_font_chars >= max(2, int(len(text) * 0.35)):
        return True
    if equation_number and (strong_operator or math_font_chars >= 2):
        return True
    if len(text) <= 180 and word_count <= 18 and strong_operator and math_symbols >= 1:
        return True
    if len(text) <= 120 and superscript_chars >= 2 and math_symbols >= 1 and word_count <= 6 and strong_operator:
        return True
    return False


def merge_caption_blocks(caption: base.Block, continuation: base.Block) -> None:
    left, right = caption.text.rstrip(), continuation.text.lstrip()
    caption.text = base.norm(left[:-1] + right) if left.endswith("-") and re.match(r"^[a-z]", right) else base.norm(left + " " + right)
    caption.lines.extend(continuation.lines)
    caption.spans.extend(continuation.spans)
    # Deliberately preserve the first fragment bbox. A bottom-left legend continued
    # at top-right must remain anchored at the bottom of its source figure page.
    sizes = [span.size for span in caption.spans if 4 <= span.size <= 30]
    caption.median_size = statistics.median(sizes) if sizes else caption.median_size
    caption.max_size = max(sizes) if sizes else caption.max_size
    caption.source_sha256 = base.digest(caption.text)


def render_crop(doc: fitz.Document, block: base.Block, previous_caption_y: dict[int, float], scale: float = 1.6):
    return ORIGINAL_RENDER_CROP(doc, block, previous_caption_y, scale=max(float(scale), 3.0))


def layout_reference_candidates(doc: fitz.Document) -> dict[int, str]:
    start_re = re.compile(r"(?<!\S)(\d{1,3})\.\s+(?=[A-Za-z\[])")
    heading_re = re.compile(r"^References(?:\s+and\s+Notes)?\b\s*", re.I)

    def columns(page: fitz.Page) -> dict[str, list[tuple[float, float, str]]]:
        out: dict[str, list[tuple[float, float, str]]] = {"left": [], "right": [], "full": []}
        for raw in page.get_text("blocks", sort=False):
            x0, y0, x1, y1, text = raw[:5]
            clean = base.norm(text)
            if not clean:
                continue
            if y0 < page.rect.height * 0.055 and ("doi.org" in clean.lower() or clean.lower().startswith(("article", "research article"))):
                continue
            if y0 > page.rect.height * 0.92 and re.search(r"(?:Nature|Cell|Science).*\d{4}", clean):
                continue
            center, width = (x0 + x1) / 2, x1 - x0
            col = "full" if width > page.rect.width * 0.62 or (x0 < page.rect.width * 0.27 and x1 > page.rect.width * 0.73) else ("left" if center < page.rect.width * 0.5 else "right")
            out[col].append((float(y0), float(x0), clean))
        return out

    def joined(items: list[tuple[float, float, str]]) -> str:
        return base.norm(" ".join(text for _y, _x, text in sorted(items, key=lambda item: (item[0], item[1]))))

    seed_page: int | None = None
    seed_col: str | None = None
    seed_y = 0.0
    explicit = False
    for page_index, page in enumerate(doc):
        for col, items in columns(page).items():
            for y0, _x0, clean in items:
                if heading_re.match(clean):
                    seed_page, seed_col, seed_y, explicit = page_index, col, y0, True
                    break
            if seed_page is not None:
                break
        if seed_page is not None:
            break
    if seed_page is None:
        for page_index, page in enumerate(doc):
            for col, items in columns(page).items():
                nums = [int(m.group(1)) for m in start_re.finditer(joined(items))]
                needed = 1
                for value in nums:
                    if value == needed:
                        needed += 1
                        if needed == 5:
                            break
                if needed == 5:
                    seed_page, seed_col = page_index, col
                    break
            if seed_page is not None:
                break
    if seed_page is None:
        return {}

    candidates: dict[int, list[tuple[int, str]]] = {}
    stop_re = re.compile(r"^(?:Acknowledg(?:e)?ments|Author contributions|Competing interests|Declaration of interests|Funding|Additional information|Supplemental information|Supplementary information)\b", re.I)
    source_re = re.compile(r"\b(?:Nature|Cell|Science|Cancer|IEEE|Proc\.|J\.|Nat\.|Med\.|Res\.|Rev\.|Bioinformatics|Springer|PMLR|Zenodo|arXiv|Immunity|Neuro|Oncol|Lancet|Front\.|Commun\.|Genome|Nucleic|BioRxiv|Preprint)\b", re.I)
    for page_index in range(seed_page, len(doc)):
        for col in ("left", "right", "full"):
            items = columns(doc[page_index])[col]
            if not items:
                continue
            filtered = []
            for y0, x0, text in items:
                if page_index == seed_page and explicit and col == seed_col and y0 < seed_y:
                    continue
                if page_index == seed_page and explicit and col == seed_col:
                    text = heading_re.sub("", text, count=1)
                    if not text:
                        continue
                filtered.append((y0, x0, text))
            text = joined(filtered)
            matches = list(start_re.finditer(text))
            for i, match in enumerate(matches):
                number = int(match.group(1))
                if not 1 <= number <= 400:
                    continue
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                segment = base.norm(text[match.end():end])
                stop = stop_re.search(segment)
                if stop:
                    segment = base.norm(segment[:stop.start()])
                if len(segment) < 18 or segment.lower().startswith(("http://", "https://", "doi")):
                    continue
                has_year = bool(re.search(r"(?:19|20)\d{2}", segment))
                has_doi = bool(base.DOI_RE.search(segment) or base.URL_RE.search(segment))
                author_like = bool(re.search(r"^[^.;]{1,220}(?:,|\bet al\.|\band\b|&)", segment, re.I))
                source_like = bool(source_re.search(segment))
                valid = (author_like or source_like or has_year or has_doi) if explicit else ((has_year or has_doi) and (author_like or source_like))
                if not valid:
                    continue
                score = (6 if has_year else 0) + (5 if has_doi else 0) + (4 if author_like else 0) + (3 if source_like else 0) + min(len(segment), 600) // 100
                candidates.setdefault(number, []).append((score, segment))
    best = {n: max(values, key=lambda item: (item[0], len(item[1])))[1] for n, values in candidates.items()}
    result: dict[int, str] = {}
    n = 1
    while n in best:
        result[n] = best[n]
        n += 1
    return result


def parse_references(events: list[base.Event], doc: fitz.Document | None = None) -> list[dict[str, Any]]:
    joined = " ".join(base.norm(e.text) for e in events if e.kind == "reference" and base.norm(e.text))
    starts = list(re.finditer(r"(?<!\S)(\d{1,3})[.\t]\s*(?=[A-Za-z\[])", joined))
    refs: dict[int, str] = {}
    for i, match in enumerate(starts):
        number = int(match.group(1))
        if not 1 <= number <= 400:
            continue
        end = starts[i + 1].start() if i + 1 < len(starts) else len(joined)
        text = base.norm(joined[match.end():end])
        if text:
            refs[number] = text
    if doc is not None:
        for number, text in layout_reference_candidates(doc).items():
            existing = refs.get(number, "")
            existing_bib = bool(re.search(r"\([^)]*(?:19|20)\d{2}[^)]*\)", existing) or base.DOI_RE.search(existing))
            candidate_bib = bool(re.search(r"\([^)]*(?:19|20)\d{2}[^)]*\)", text) or base.DOI_RE.search(text))
            if not existing or (candidate_bib and not existing_bib) or (len(text) > len(existing) * 1.25 and candidate_bib):
                refs[number] = text
    result: dict[int, str] = {}
    n = 1
    while n in refs:
        result[n] = refs[n]
        n += 1
    return [base.reference_item(n, result[n]) for n in sorted(result)]


ORIGINAL_AUGMENT_AUDIT = final.augment_audit


def augment_audit(audit: dict[str, Any], manifest: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    audit = ORIGINAL_AUGMENT_AUDIT(audit, manifest, source)
    expected = int(source.get("expected_reference_count", 0) or 0)
    ids = [int(item.get("id", 0)) for item in manifest.get("references", [])]
    exact_errors = []
    if expected and len(ids) != expected:
        exact_errors.append(f"reference coverage mismatch: {len(ids)} != {expected}")
    if expected and ids != list(range(1, expected + 1)):
        exact_errors.append({"reference_id_sequence": {"expected": [1, expected], "actual_head": ids[:10], "actual_tail": ids[-10:]}})
    if exact_errors:
        audit["strict_errors"] = list(audit.get("strict_errors") or []) + exact_errors
        audit["passed"] = False
    audit["strict_layout_parser"] = "v082-final-3"
    audit["reader_grade_crop_scale"] = 3.0
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description="Build strict V0.8.2 PDF-native manifest (final v3)")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()

    final.reset_metrics()
    registry = json.loads(args.registry.read_text("utf-8"))
    source = next(item for item in registry["papers"] if item["key"] == args.key)
    with fitz.open(args.pdf) as document:
        final.PAGE_HEIGHTS.clear()
        final.PAGE_HEIGHTS.update({index + 1: float(page.rect.height) for index, page in enumerate(document)})

    final.is_formula_block = is_formula_block
    final.merge_caption_blocks = merge_caption_blocks
    final.augment_audit = augment_audit
    base.classify = final.strict_classify
    base.should_merge = final.strict_should_merge
    base.page_reading_order = final.strict_page_reading_order
    base.render_crop = render_crop
    base.pdf_reference_candidates = layout_reference_candidates
    base.parse_references = parse_references

    temporary = args.audit.with_suffix(args.audit.suffix + ".base") if args.audit else None
    manifest = base.build_manifest(args.pdf, source, temporary)
    audit = json.loads(temporary.read_text("utf-8")) if temporary and temporary.exists() else {}
    if temporary and temporary.exists():
        temporary.unlink()
    audit = augment_audit(audit, manifest, source)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", "utf-8")
    if args.audit:
        args.audit.parent.mkdir(parents=True, exist_ok=True)
        args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"key": args.key, "sections": len(manifest.get("sections", [])), "paragraphs": audit.get("paragraphs"), "assets": len(manifest.get("assets", [])), "references": len(manifest.get("references", [])), "formula_blocks": final.METRICS["formula_blocks_detected"], "cross_column_caption_merges": final.METRICS["cross_column_caption_merges"], "passed": audit.get("passed"), "errors": audit.get("strict_errors", [])}, ensure_ascii=False, indent=2))
    if not audit.get("passed"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
