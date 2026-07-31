#!/usr/bin/env python3
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import generate_v082_reader_manifest_with_copilot_sdk_v16 as v16


v13 = v16.v13
# Preserve scientific abbreviations themselves without treating adjacent English
# hyphenation punctuation as part of the abbreviation (for example TME-determined).
v13.ABBREVIATION = re.compile(
    r"\b[A-Z][A-Z0-9α-ωΑ-Ω]*(?:[./+\-][A-Z0-9α-ωΑ-Ω]+)*\b"
)
_ORIGINAL_VALIDATE_TRANSLATION = v13.validate_translation
_ORIGINAL_TRANSLATE_ONE = v13.translate_one
_CURRENT_ITEM_ID = ""
SHORT_TITLE_PREFIXES = ("section-title/", "asset-title/")

# PDF extraction commonly flattens superscript bibliography citations into the
# surrounding prose, for example meningiomas2, proposed4–12, enrichment6,9 or
# ``et al.62``. Those IDs are carried separately in citation_ids and are validated
# by the manifest/semantic gates. They must not be treated as measurements.
EXPLICIT_REFERENCE = re.compile(
    r"\brefs?\.?\s*\d+(?:\s*[–—-]\s*\d+)?(?:\s*,\s*\d+(?:\s*[–—-]\s*\d+)?)*",
    re.I,
)
AFTER_PERIOD_REFERENCE = re.compile(
    r"(?P<prefix>[A-Za-z]\.)"
    r"(?P<cites>\d+(?:[–—-]\d+)?(?:,\d+(?:[–—-]\d+)?)*)"
    r"(?=$|[\s,.;:)\]])"
)
ATTACHED_REFERENCE = re.compile(
    r"(?P<prefix>[A-Za-z\)])"
    r"(?P<cites>\d+(?:[–—-]\d+)?(?:,\d+(?:[–—-]\d+)?)*)"
    r"(?=$|[\s,.;:)\]])"
)
PAREN_REFERENCE_ONLY = re.compile(
    r"\(\s*\d+(?:\s*[–—-]\s*\d+)?(?:\s*,\s*\d+(?:\s*[–—-]\s*\d+)?)*\s*\)"
)


def is_short_title_component(item_id: str) -> bool:
    return any(str(item_id).startswith(prefix) for prefix in SHORT_TITLE_PREFIXES)


def strip_inline_reference_ids(value: str) -> str:
    """Remove flattened reference IDs while retaining scientific numbers."""
    text = str(value or "")
    text = EXPLICIT_REFERENCE.sub(" ", text)
    text = PAREN_REFERENCE_ONLY.sub(" ", text)
    previous = None
    while previous != text:
        previous = text
        text = AFTER_PERIOD_REFERENCE.sub(lambda match: match.group("prefix"), text)
        text = ATTACHED_REFERENCE.sub(lambda match: match.group("prefix"), text)
    return text


def scientific_number_issues(source: str, chinese: str) -> list[str]:
    source_text = strip_inline_reference_ids(source)
    target_text = strip_inline_reference_ids(chinese)
    source_numbers = Counter(
        token.replace(" ", "") for token in v13.NUMBER.findall(source_text)
    )
    target_numbers = Counter(
        token.replace(" ", "") for token in v13.NUMBER.findall(target_text)
    )
    return [
        f"number not preserved: {token}"
        for token, count in source_numbers.items()
        if target_numbers[token] < count
    ]


def component_translation_issues(item_id: str, source: str, chinese: str) -> list[str]:
    """Apply completeness rules appropriate to the actual content component.

    Body paragraphs, legends and table cells keep the full length/completeness
    gate. Scientific headings are allowed to be concise Chinese equivalents such
    as Abstract→摘要 and Results→结果. Bibliography IDs flattened into PDF text
    are excluded from the scientific-number gate because citation_ids are carried
    and validated independently in the manifest.
    """
    issues = [
        issue
        for issue in _ORIGINAL_VALIDATE_TRANSLATION(source, chinese)
        if not issue.startswith("number not preserved:")
    ]
    issues.extend(scientific_number_issues(source, chinese))
    if is_short_title_component(item_id):
        cjk_count = len(v13.CJK.findall(str(chinese or "")))
        if cjk_count >= 2:
            issues = [issue for issue in issues if issue != "translation implausibly short"]
    return issues


def validate_translation_with_component_context(source: str, chinese: str) -> list[str]:
    return component_translation_issues(_CURRENT_ITEM_ID, source, chinese)


def translate_one_with_component_context(
    source: str,
    *,
    item_id: str,
    paper_title: str,
    token: str,
    primary_model: str,
    reviewer_model: str,
    cache_dir: Path,
) -> str:
    global _CURRENT_ITEM_ID
    previous = _CURRENT_ITEM_ID
    _CURRENT_ITEM_ID = str(item_id)
    try:
        return _ORIGINAL_TRANSLATE_ONE(
            source,
            item_id=item_id,
            paper_title=paper_title,
            token=token,
            primary_model=primary_model,
            reviewer_model=reviewer_model,
            cache_dir=cache_dir,
        )
    finally:
        _CURRENT_ITEM_ID = previous


v13.validate_translation = validate_translation_with_component_context
v13.translate_one = translate_one_with_component_context


if __name__ == "__main__":
    v13.main()
