#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import Any

import validate_v082_evidence_quality_v4 as base

base.CAPTION_START = re.compile(
    r"^(?:Fig\.?|Figure|Extended Data Fig\.?|Supplementary Fig(?:ure)?|Table)\s+[A-Za-z]?\d+(?:\s*[|.]|\s+[A-Z])",
    re.I,
)
ORIGINAL_VALIDATE = base.validate
BACK_MATTER = {
    "methods", "star methods", "materials and methods", "resource availability", "lead contact",
    "materials availability", "data and code availability", "data availability", "code availability",
    "acknowledgements", "acknowledgments", "author contributions", "declaration of interests",
    "competing interests", "additional information", "references", "online content", "key resources table",
    "quantification and statistical analysis", "additional resources", "limitations of the study",
}


def key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def validate(manifest: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    result = ORIGINAL_VALIDATE(manifest, audit)
    errors = result["errors"]
    sections = manifest.get("sections") or []
    keys = [key(section.get("title_en")) for section in sections]
    errors[:] = [
        error for error in errors
        if not (
            isinstance(error, dict)
            and error.get("path") in {"sections", "evidence_outline"}
            and error.get("issue") in {
                "Results or the first source result section is missing",
                "Results section is missing from source outline",
            }
        )
    ]
    try:
        intro_index = keys.index("introduction")
    except ValueError:
        intro_index = -1
    try:
        discussion_index = keys.index("discussion")
    except ValueError:
        discussion_index = len(keys)
    scientific_between = [
        section for index, section in enumerate(sections)
        if index > intro_index and index < discussion_index
        and key(section.get("title_en")) not in BACK_MATTER
        and any(block.get("type") == "paragraph" for block in section.get("blocks", []))
    ]
    if intro_index < 0 or not scientific_between:
        errors.append({
            "path": "sections",
            "issue": "no scientific result section with body paragraphs appears between Introduction and Discussion",
            "value": [section.get("title_en") for section in sections],
        })
    result["version"] = "v082-evidence-quality-5"
    result["scientific_result_sections"] = [section.get("title_en") for section in scientific_between]
    result["passed"] = not errors
    return result


base.validate = validate
base.base.validate = validate
base.base.base.validate = validate


if __name__ == "__main__":
    base.base.base.main()
