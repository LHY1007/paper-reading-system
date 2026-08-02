#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import Any

import validate_v082_evidence_quality_v3 as base

ORIGINAL_VALIDATE = base.validate
PARSER_RE = re.compile(r"^v082-final-(?:1[5-9]|[2-9]\d+)$")
BODY_VERSION_RE = re.compile(r"^v082-body-reconstruction-(?:[5-9]|[1-9]\d+)$")
CAPTION_START = re.compile(r"^(?:Fig\.?|Figure|Extended Data Fig\.?|Supplementary Fig(?:ure)?|Table)\s+[A-Za-z]?\d+", re.I)
BACK_MATTER_START = re.compile(r"^(?:Downloaded from|Publisher[’']s note|Open Access This article|This is an open access article)", re.I)
REFERENCE_START = re.compile(r"^(?:\d{1,3}[. ]+)?[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’\-]+(?:,|\s+[A-Z]\.)[^.!?]{0,120}\bet al\.", re.I)
LABEL_CLOUD = re.compile(r"^(?:[A-Za-z0-9+−–./()%]+\s+){10,}[A-Za-z0-9+−–./()%]+$")


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def paragraph_text(block: dict[str, Any]) -> str:
    return norm("".join(str(item.get("text", "")) for item in block.get("english", [])))


def add(errors: list[dict[str, Any]], path: str, issue: str, value: Any = None) -> None:
    item: dict[str, Any] = {"path": path, "issue": issue}
    if value is not None:
        item["value"] = value if isinstance(value, (int, float, bool, list, dict)) else norm(value)[:800]
    errors.append(item)


def validate(manifest: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    result = ORIGINAL_VALIDATE(manifest, audit)
    errors = result["errors"]
    parser_version = norm(audit.get("strict_layout_parser"))
    if not PARSER_RE.fullmatch(parser_version):
        add(errors, "audit.strict_layout_parser", "body-safe parser v15 or newer is required", parser_version)

    diagnostics = manifest.get("evidence_body_reconstruction") or {}
    body_version = norm(diagnostics.get("version"))
    if not BODY_VERSION_RE.fullmatch(body_version):
        add(errors, "evidence_body_reconstruction.version", "page-aware body reconstruction v5 or newer is required", body_version)

    low_pages = diagnostics.get("low_coverage_pages") or []
    if low_pages:
        add(errors, "evidence_body_reconstruction.low_coverage_pages", "one or more scientific pages lost qualifying body text", low_pages)
    candidate_chars = int(diagnostics.get("candidate_source_chars", 0) or 0)
    accepted_chars = int(diagnostics.get("accepted_source_chars", 0) or 0)
    if candidate_chars <= 0:
        add(errors, "evidence_body_reconstruction.candidate_source_chars", "no body candidates were measured")
    elif accepted_chars / candidate_chars < 0.98:
        add(errors, "evidence_body_reconstruction.accepted_source_chars", "less than 98% of qualifying body evidence was retained", {
            "candidate": candidate_chars,
            "accepted": accepted_chars,
            "ratio": round(accepted_chars / candidate_chars, 4),
        })

    page_candidates = {str(key): int(value) for key, value in (diagnostics.get("page_candidate_chars") or {}).items()}
    page_accepted = {str(key): int(value) for key, value in (diagnostics.get("page_source_chars") or {}).items()}
    if page_candidates and set(page_candidates) != set(page_accepted):
        add(errors, "evidence_body_reconstruction.page_source_chars", "candidate and retained scientific page inventories differ", {
            "candidate_pages": sorted(page_candidates),
            "accepted_pages": sorted(page_accepted),
        })
    for page, total in page_candidates.items():
        retained = page_accepted.get(page, 0)
        if total >= 200 and retained / max(1, total) < 0.92:
            add(errors, f"evidence_body_reconstruction.page_coverage.{page}", "page-level body coverage is below 92%", {
                "candidate": total,
                "accepted": retained,
                "ratio": round(retained / total, 4),
            })

    sections = manifest.get("sections") or []
    paragraphs = [
        (section, block, paragraph_text(block))
        for section in sections
        for block in section.get("blocks", [])
        if block.get("type") == "paragraph"
    ]
    section_keys = {re.sub(r"[^a-z0-9]+", " ", norm(section.get("title_en")).lower()).strip() for section in sections}
    if "introduction" not in section_keys:
        add(errors, "sections", "Introduction is missing from reconstructed body")
    if not any(key == "results" or key.startswith("giga") or "study cohort" in key for key in section_keys):
        add(errors, "sections", "Results or the first source result section is missing")
    if "discussion" not in section_keys:
        add(errors, "sections", "Discussion is missing from reconstructed body")

    contaminated: list[dict[str, Any]] = []
    short_fragments: list[dict[str, Any]] = []
    for section, block, text in paragraphs:
        block_id = str(block.get("id") or "unknown")
        path = f"sections.{section.get('id')}.{block_id}"
        issue = None
        if CAPTION_START.match(text):
            issue = "figure or table caption was retained as body"
        elif BACK_MATTER_START.match(text):
            issue = "publisher or download footer was retained as body"
        elif REFERENCE_START.match(text) and re.search(r"\b(?:19|20)\d{2}\b", text):
            issue = "bibliographic reference was retained as body"
        else:
            alpha = sum(character.isalpha() for character in text)
            digits = sum(character.isdigit() for character in text)
            word_count = len(re.findall(r"\b\w+\b", text))
            if word_count >= 12 and LABEL_CLOUD.fullmatch(text) and not re.search(r"[.!?;:]", text):
                issue = "figure-axis or label cloud was retained as body"
            elif len(text) >= 120 and alpha / max(1, len(text)) < 0.42:
                issue = "body paragraph is dominated by non-prose symbols or labels"
            elif len(text) >= 120 and digits / max(1, len(text)) > 0.23:
                issue = "body paragraph is dominated by numeric figure labels"
        if issue:
            contaminated.append({"path": path, "issue": issue, "text": text[:500]})
        if len(text) < 45 and not re.search(r"[=∑∫√∂]", text):
            short_fragments.append({"path": path, "text": text})
    if contaminated:
        add(errors, "sections.blocks", "non-body content remains in reconstructed paragraphs", contaminated[:40])
    if len(short_fragments) > max(3, len(paragraphs) // 20):
        add(errors, "sections.blocks", "too many sentence or label fragments remain", short_fragments[:40])

    manifest_source_chars = sum(len(text) for _, _, text in paragraphs)
    diagnostic_source_chars = int(diagnostics.get("source_chars", -1))
    if diagnostic_source_chars != manifest_source_chars:
        add(errors, "evidence_body_reconstruction.source_chars", "body diagnostic and manifest character counts differ", {
            "diagnostic": diagnostic_source_chars,
            "manifest": manifest_source_chars,
        })
    if int(audit.get("source_chars", -1)) != manifest_source_chars:
        add(errors, "audit.source_chars", "audit and reconstructed manifest character counts differ", {
            "audit": audit.get("source_chars"),
            "manifest": manifest_source_chars,
        })
    if int(audit.get("paragraphs", -1)) != len(paragraphs):
        add(errors, "audit.paragraphs", "audit and reconstructed paragraph counts differ", {
            "audit": audit.get("paragraphs"),
            "manifest": len(paragraphs),
        })

    result.update({
        "version": "v082-evidence-quality-4",
        "body_reconstruction": body_version,
        "body_paragraphs": len(paragraphs),
        "body_source_chars": manifest_source_chars,
        "body_candidate_chars": candidate_chars,
        "body_accepted_chars": accepted_chars,
        "body_pages": sorted(int(page) for page in page_accepted),
        "body_low_coverage_pages": low_pages,
        "body_contamination_count": len(contaminated),
        "body_short_fragment_count": len(short_fragments),
        "passed": not errors,
    })
    return result


base.validate = validate
base.base.validate = validate


if __name__ == "__main__":
    base.base.main()
