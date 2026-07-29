#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import Any

import validate_v082_evidence_quality as base


ORIGINAL_VALIDATE = base.validate
PLACEHOLDERS = {"authors listed in the source pdf", "unknown", "author", "slides"}


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def validate(manifest: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    result = ORIGINAL_VALIDATE(manifest, audit)
    errors = result["errors"]
    paper = manifest.get("paper") or {}
    authors = [norm(value) for value in paper.get("authors") or [] if norm(value)]
    affiliations = [norm(value) for value in paper.get("affiliations") or [] if norm(value)]
    publisher = norm(paper.get("publisher"))
    timeline = norm(paper.get("publication_timeline"))

    if len(authors) < 2 or any(value.lower() in PLACEHOLDERS for value in authors):
        errors.append({
            "path": "paper.authors",
            "issue": "complete source author names were not recovered",
            "value": authors[:20],
        })
    if not affiliations:
        errors.append({
            "path": "paper.affiliations",
            "issue": "numbered source affiliations were not recovered",
        })
    if not publisher:
        errors.append({
            "path": "paper.publisher",
            "issue": "publisher evidence is missing",
        })
    if not timeline or not re.search(r"(?:Received|Accepted|Published online)", timeline, re.I):
        errors.append({
            "path": "paper.publication_timeline",
            "issue": "source publication dates were not recovered",
            "value": timeline,
        })

    repairs = manifest.get("evidence_repairs") or {}
    if int(repairs.get("authors_extracted", len(authors)) or 0) != len(authors):
        errors.append({
            "path": "evidence_repairs.authors_extracted",
            "issue": "author repair report is inconsistent with the manifest",
        })
    if int(repairs.get("affiliations_extracted", len(affiliations)) or 0) != len(affiliations):
        errors.append({
            "path": "evidence_repairs.affiliations_extracted",
            "issue": "affiliation repair report is inconsistent with the manifest",
        })

    result["version"] = "v082-evidence-quality-3"
    result["authors"] = len(authors)
    result["affiliations"] = len(affiliations)
    result["publisher"] = publisher
    result["publication_timeline"] = timeline
    result["passed"] = not errors
    return result


base.validate = validate


if __name__ == "__main__":
    base.main()
