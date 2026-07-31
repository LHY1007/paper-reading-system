#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import generate_v082_reader_manifest_with_copilot_sdk_v17 as v17


v13 = v17.v13
_ORIGINAL_TEXT_CALL = v13.base.call_model_json
_ORIGINAL_MULTIMODAL_CALL = v13.call_multimodal_json
_ORIGINAL_POSTPROCESS = v13.postprocess_manifest
REVIEW_RESPONSES: dict[str, dict[str, Any]] = {
    "translation": {},
    "figure": {},
    "table": {},
    "overview": {},
}


def norm(value: Any) -> str:
    return v13.norm(value)


def record_text_review(*args, **kwargs):
    result = _ORIGINAL_TEXT_CALL(*args, **kwargs)
    cache_name = str(kwargs.get("cache_name") or "")
    payload = kwargs.get("user_payload") or {}
    if cache_name.startswith("translation-review-") or cache_name.startswith("translation-repair-"):
        item_id = str(payload.get("id") or "")
        if item_id:
            REVIEW_RESPONSES["translation"][item_id] = result
    elif cache_name == "overview-review":
        REVIEW_RESPONSES["overview"]["paper"] = result
    return result


def record_multimodal_review(*args, **kwargs):
    result = _ORIGINAL_MULTIMODAL_CALL(*args, **kwargs)
    cache_name = str(kwargs.get("cache_name") or "")
    payload = kwargs.get("payload") or {}
    if cache_name.startswith("figure-review-") or cache_name.startswith("figure-repair-"):
        source = payload.get("source") or {}
        item_id = str(source.get("id") or "")
        if item_id:
            REVIEW_RESPONSES["figure"][item_id] = result
    elif cache_name.startswith("table-review-"):
        source = payload.get("source") or {}
        item_id = str(source.get("id") or "")
        if item_id:
            REVIEW_RESPONSES["table"][item_id] = result
    return result


def reviewer_accepted(result: Any) -> bool:
    return isinstance(result, dict) and result.get("passed") is True


def enforce_independent_reviewer_acceptance(review_log: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for category in ("translation", "figure", "table"):
        for item in review_log.get(category) or []:
            item_id = str(item.get("id") or "")
            response = REVIEW_RESPONSES[category].get(item_id)
            accepted = reviewer_accepted(response)
            item["independent_reviewer_accepted"] = accepted
            if not accepted:
                errors.append({
                    "component": category,
                    "id": item_id,
                    "issue": "independent reviewer did not explicitly accept the final corrected component",
                    "review_response_present": response is not None,
                })

    overview_response = REVIEW_RESPONSES["overview"].get("paper")
    overview_accepted = reviewer_accepted(overview_response)
    review_log.setdefault("overview", {})["independent_reviewer_accepted"] = overview_accepted
    if not overview_accepted:
        errors.append({
            "component": "overview",
            "id": "paper",
            "issue": "independent reviewer did not explicitly accept the final overview",
            "review_response_present": overview_response is not None,
        })
    return errors


def postprocess_with_acceptance(
    evidence_path: Path,
    plan_path: Path,
    output_path: Path,
    cache_dir: Path,
) -> None:
    _ORIGINAL_POSTPROCESS(evidence_path, plan_path, output_path, cache_dir)
    errors = enforce_independent_reviewer_acceptance(v13.REVIEW_LOG)
    if errors:
        v13.REVIEW_LOG.setdefault("errors", []).extend(errors)
        v13.REVIEW_LOG["passed"] = False
    else:
        v13.REVIEW_LOG["independent_reviewer_acceptance_passed"] = True
        v13.REVIEW_LOG["passed"] = bool(v13.REVIEW_LOG.get("passed"))

    review_path = output_path.with_suffix(".strong-ai-review.json")
    review_path.write_text(
        json.dumps(v13.REVIEW_LOG, ensure_ascii=False, indent=2) + "\n",
        "utf-8",
    )
    if errors:
        raise RuntimeError(
            "independent reviewer acceptance gate failed: "
            + json.dumps(errors[:12], ensure_ascii=False)
        )


v13.base.call_model_json = record_text_review
v13.call_multimodal_json = record_multimodal_review
v13.postprocess_manifest = postprocess_with_acceptance


if __name__ == "__main__":
    v13.main()
