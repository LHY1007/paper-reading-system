#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

import generate_v082_reader_manifest_with_copilot_sdk_v16 as v16


v13 = v16.v13
_ORIGINAL_VALIDATE_TRANSLATION = v13.validate_translation
_ORIGINAL_TRANSLATE_ONE = v13.translate_one
_CURRENT_ITEM_ID = ""
SHORT_TITLE_PREFIXES = ("section-title/", "asset-title/")


def is_short_title_component(item_id: str) -> bool:
    return any(str(item_id).startswith(prefix) for prefix in SHORT_TITLE_PREFIXES)


def component_translation_issues(item_id: str, source: str, chinese: str) -> list[str]:
    """Apply completeness rules appropriate to the actual content component.

    Body paragraphs, legends and table cells keep the full length/completeness gate.
    Scientific headings are allowed to be concise Chinese equivalents such as
    Abstract→摘要 and Results→结果, while number/abbreviation preservation and the
    requirement for real Chinese text remain unchanged.
    """
    issues = list(_ORIGINAL_VALIDATE_TRANSLATION(source, chinese))
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
