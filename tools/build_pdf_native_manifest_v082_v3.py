#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import Any

import build_pdf_native_manifest_v082_final as base


STAT_LABELS = {"p", "n", "hr", "or", "rr", "ci", "auc", "tps", "fdr", "q"}
PROSE_PREFIX = re.compile(r"^(?:Figure|Fig\.|Table|Data|Comparison|Scatterplot|Bars|Boxplot|Patients|Samples|Cohort|High|Low|Male|Female|Discovery|Clinical|Validation)\b", re.I)
STRONG_MATH = re.compile(r"(?:∑|∫|√|\blog\s*\(|\bln\s*\(|\bexp\s*\(|\bmax\s*\(|\bmin\s*\()", re.I)
ASSIGNMENT = re.compile(r"^\s*([A-Za-zΑ-Ωα-ω][A-Za-zΑ-Ωα-ω0-9_{}()'\- ]{0,28})\s*=\s*(\S.*)$")


def is_formula_block(block: base.base.Block) -> bool:
    text = base.base.norm(block.text)
    if not text or len(text) > 260 or base.PANEL_ONLY_RE.fullmatch(text):
        return False
    if base.base.CAPTION_RE.match(text) or base.base.DOI_RE.search(text) or base.base.URL_RE.search(text):
        return False
    low = text.lower().strip(" :")
    if low in base.base.SECTION_EXACT or base.base.REFERENCE_HEADING_RE.fullmatch(low):
        return False
    if PROSE_PREFIX.match(text):
        return False
    words = re.findall(r"[A-Za-zΑ-Ωα-ω]+", text)
    if len(words) > 18 or len(re.findall(r"[.!?;]", text)) >= 2:
        return False
    if re.match(r"^\s*(?:P|p|n|HR|OR|RR|CI|AUC|TPS|FDR|q)\s*(?:=|:|<|>|≤|≥)", text):
        return False
    assignment = ASSIGNMENT.match(text)
    if assignment:
        lhs = re.sub(r"\s+", "", assignment.group(1)).lower()
        rhs = assignment.group(2)
        if lhs not in STAT_LABELS and re.search(r"[+\-−*/×÷^_∑∫√()]|\d", rhs):
            return True
    operators = len(base.MATH_OPERATOR_RE.findall(text))
    math_font_chars = sum(len(span.text) for span in block.spans if base.MATH_FONT_RE.search(span.font))
    if STRONG_MATH.search(text) and operators >= 1 and len(words) <= 14:
        return True
    if re.search(r"\(\s*\d{1,2}\s*\)\s*$", text) and operators >= 1 and len(words) <= 14:
        return True
    if math_font_chars >= max(4, int(len(text) * 0.35)) and operators >= 2 and len(words) <= 12:
        return True
    return False


ORIGINAL_AUGMENT = base.augment_audit


def augment_audit(audit: dict[str, Any], manifest: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    result = ORIGINAL_AUGMENT(audit, manifest, source)
    result["strict_layout_parser"] = "v082-final-3"
    return result


base.is_formula_block = is_formula_block
base.augment_audit = augment_audit


def main() -> None:
    base.main()


if __name__ == "__main__":
    main()
