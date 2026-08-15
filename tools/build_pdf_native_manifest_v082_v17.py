#!/usr/bin/env python3
from __future__ import annotations

"""V0.8.2 PDF-native parser v17.

Layers the v16 metadata/body/figure/reference recovery on the strict layout parser,
then fixes the remaining regression cases found by sequential source-PDF audit:
- cross-column captions keep the first-fragment crop anchor;
- source figures render at 3x for the full-width figure reader;
- statistical plot labels are not misclassified as display equations;
- primary paper authors are preferred over appended consortium-member inventories;
- reference IDs must be exactly 1..N, not merely at least N entries.
"""

import re
import statistics
import unicodedata
from typing import Any

import build_pdf_native_manifest_v082_v16 as v16

final = v16.base
base = final.base
ORIGINAL_RENDER_CROP = base.render_crop
ORIGINAL_AUGMENT = v16.augment
ORIGINAL_BUILD = v16.build


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
    return bool(len(text) <= 120 and superscript_chars >= 2 and math_symbols >= 1 and word_count <= 6 and strong_operator)


def merge_caption_blocks(caption: base.Block, continuation: base.Block) -> None:
    left, right = caption.text.rstrip(), continuation.text.lstrip()
    caption.text = base.norm(left[:-1] + right) if left.endswith("-") and re.match(r"^[a-z]", right) else base.norm(left + " " + right)
    caption.lines.extend(continuation.lines)
    caption.spans.extend(continuation.spans)
    sizes = [span.size for span in caption.spans if 4 <= span.size <= 30]
    caption.median_size = statistics.median(sizes) if sizes else caption.median_size
    caption.max_size = max(sizes) if sizes else caption.max_size
    caption.source_sha256 = base.digest(caption.text)


def render_crop(doc, block, previous_caption_y, scale: float = 1.6):
    return ORIGINAL_RENDER_CROP(doc, block, previous_caption_y, scale=max(float(scale), 3.0))


def _fold(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch)).lower()


def _group_author_tokens(text: str) -> list[tuple[int, str]]:
    pattern = re.compile(
        r"\b([A-Z][A-Za-zÀ-ÖØ-öø-ÿ&'’.-]*(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ&'’.-]*){0,6}\s+"
        r"(?:Consortium|Collaborative|Collaboration|Investigators|Study Group|Research Group|Network|Working Group|Team))\*?\b"
    )
    return [(match.start(), base.norm(match.group(1))) for match in pattern.finditer(text)]


def primary_authors(doc, correspondence: str) -> list[str]:
    options: list[tuple[float, int, int, int, list[str], str]] = []
    email_surnames = []
    for email in re.findall(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+", correspondence):
        local = email.split("@", 1)[0]
        email_surnames.append(_fold(local.split(".")[-1]))
    for page_index in range(len(doc)):
        for _block_index, b in enumerate(doc[page_index].get_text("blocks", sort=False)):
            value = v16.N(str(b[4]).replace("\xad", ""))
            if len(value) < 35 or value.count(",") < 2:
                continue
            if re.match(r"^(?:References?\b|\d{1,3}\.\s|Methods?\b|Acknowledg|Author contributions|Competing interests)", value, re.I):
                continue
            matches = list(v16.AFIRST.finditer(value))
            if len(matches) < 2:
                continue
            coverage = sum(match.end() - match.start() for match in matches) / max(1, len(value))
            if coverage < 0.48:
                continue
            got = v16.parse_authors(value, correspondence)
            if not (2 <= len(got) <= 60):
                continue
            folded_value = _fold(value)
            correspondent_hits = sum(bool(name and name in folded_value) for name in email_surnames)
            groups = _group_author_tokens(value)
            if groups:
                ordered: list[tuple[int, str]] = [(m.start(), v16.N(m.group(1))) for m in matches]
                ordered.extend(groups)
                ordered.sort(key=lambda item: item[0])
                dedup: list[str] = []
                for _pos, name in ordered:
                    if name and name not in dedup:
                        dedup.append(name)
                last = v16.ALAST.search(value)
                if last:
                    lname = v16.N(last.group(1))
                    if lname and lname not in dedup:
                        dedup.append(lname)
                got = dedup
            options.append((coverage, correspondent_hits, len(matches), -len(value), got, value))
    if not options:
        return []
    options.sort(key=lambda item: (item[0], item[1], item[2], item[3]), reverse=True)
    return options[0][4]


def build(pdf, source: dict[str, Any], audit_path=None) -> dict[str, Any]:
    manifest = ORIGINAL_BUILD(pdf, source, audit_path)
    with __import__("fitz").open(pdf) as doc:
        paper = manifest.get("paper") or {}
        recovered = primary_authors(doc, base.norm(paper.get("correspondence")))
    if recovered:
        paper["authors"] = recovered
        manifest["paper"] = paper
        repairs = manifest.get("evidence_repairs") or {}
        repairs.update({
            "primary_author_override_v17": True,
            "authors_extracted": len(recovered),
            "primary_author_source": "compact-affiliation-tagged-byline",
        })
        manifest["evidence_repairs"] = repairs
    return manifest


def augment(audit: dict[str, Any], manifest: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    result = ORIGINAL_AUGMENT(audit, manifest, source)
    expected = int(source.get("expected_reference_count", 0) or 0)
    ids = [int(item.get("id", 0)) for item in manifest.get("references", [])]
    errors = list(result.get("strict_errors") or [])
    if expected and len(ids) != expected:
        errors.append(f"reference coverage mismatch: {len(ids)} != {expected}")
    if expected and ids != list(range(1, expected + 1)):
        errors.append({"reference_id_sequence": {"expected": [1, expected], "actual_head": ids[:10], "actual_tail": ids[-10:]}})
    result.update({
        "strict_layout_parser": "v082-final-17",
        "reader_grade_crop_scale": 3.0,
        "strict_errors": errors,
        "passed": not errors,
    })
    return result


v16.authors = primary_authors
v16.build = build
base.build_manifest = build
final.is_formula_block = is_formula_block
final.merge_caption_blocks = merge_caption_blocks
base.render_crop = render_crop
v16.augment = augment
final.augment_audit = augment


def main() -> None:
    v16.main()


if __name__ == "__main__":
    main()
