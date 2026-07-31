#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import validate_v082_reader_semantics_v4 as v4


CJK = re.compile(r"[\u3400-\u9fff]")
# ASCII-aware boundaries are required because Chinese characters count as \w in
# Python. A token such as TAM数量 or 26例 must still be recognized as TAM or 26.
ANCHOR = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"[A-Z][A-Z0-9.\-]{1,}|"
    r"[A-Za-z]+\d+[A-Za-z0-9.\-]*|"
    r"\d+(?:[,.]\d+)*%?|"
    r"[A-Za-z]+-[A-Za-z0-9-]+"
    r")(?![A-Za-z0-9])"
)
CURATED_FILTERABLE = {
    "panel labels/order diverge from evidence",
    "panel explanation contains no traceable source entity or value",
    "generic prose is substituting for panel-specific explanation",
}


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def digest(value: Any) -> str:
    return hashlib.sha256(norm(value).encode("utf-8")).hexdigest()


def anchors(value: Any) -> set[str]:
    return {
        token.casefold().rstrip(".")
        for token in ANCHOR.findall(norm(value))
        if len(token.rstrip(".")) >= 2
    }


def text_of(block: dict[str, Any], key: str) -> str:
    return norm("".join(str(item.get("text", "")) for item in block.get(key) or []))


def related_body(evidence: dict[str, Any]) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    for section in evidence.get("sections") or []:
        for block in section.get("blocks") or []:
            if block.get("type") != "paragraph":
                continue
            ids: list[str] = []
            for inline in block.get("english") or []:
                ids.extend(str(value) for value in inline.get("figure_ids") or [])
            for asset_id in dict.fromkeys(ids):
                output.setdefault(asset_id, []).append(text_of(block, "english"))
    return output


def audit_error(path: str, issue: str, detail: Any = None) -> dict[str, Any]:
    item: dict[str, Any] = {"path": path, "issue": issue, "severity": "error"}
    if detail is not None:
        item["detail"] = detail
    return item


def validate_curated_audit(
    manifest: dict[str, Any],
    evidence: dict[str, Any],
    audit: dict[str, Any],
) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    errors: list[dict[str, Any]] = []
    approved_assets: set[str] = set()
    approved_panels: set[str] = set()

    paper_key = norm((manifest.get("paper") or {}).get("key"))
    if audit.get("version") != "v082-curated-panel-audit-1":
        errors.append(audit_error("curated_audit.version", "unsupported curated panel audit version"))
    if norm(audit.get("paper_key")) != paper_key:
        errors.append(audit_error("curated_audit.paper_key", "curated audit paper key mismatch"))

    m_assets = {str(item.get("id")): item for item in manifest.get("assets") or []}
    e_assets = {str(item.get("id")): item for item in evidence.get("assets") or []}
    figure_ids = [asset_id for asset_id, item in e_assets.items() if item.get("kind") == "figure"]
    audited = audit.get("assets") or {}
    if set(audited) != set(figure_ids):
        errors.append(audit_error(
            "curated_audit.assets",
            "curated audit must cover every source figure exactly once",
            {"missing": sorted(set(figure_ids) - set(audited)), "extra": sorted(set(audited) - set(figure_ids))},
        ))

    related = related_body(evidence)
    for asset_id in figure_ids:
        source = e_assets[asset_id]
        target = m_assets.get(asset_id) or {}
        entry = audited.get(asset_id) or {}
        base_path = f"assets/{asset_id}"
        local_errors: list[dict[str, Any]] = []

        if entry.get("verified_from_pdf_image") is not True:
            local_errors.append(audit_error(base_path, "PDF-image panel verification is not explicit"))
        if entry.get("source_page") != source.get("source_page"):
            local_errors.append(audit_error(base_path, "curated source page differs from evidence", {
                "audit": entry.get("source_page"), "evidence": source.get("source_page")
            }))
        if norm(entry.get("title_sha256")) != digest(source.get("title_en")):
            local_errors.append(audit_error(base_path, "curated title hash differs from evidence"))
        if norm(entry.get("caption_sha256")) != digest(source.get("caption_en")):
            local_errors.append(audit_error(base_path, "curated caption hash differs from evidence"))

        expected_labels = [norm(value) or "整图" for value in entry.get("labels") or []]
        panels = (target.get("study") or {}).get("panels") or []
        actual_labels = [norm(panel.get("label")) or "整图" for panel in panels if isinstance(panel, dict)]
        if not expected_labels or actual_labels != expected_labels:
            local_errors.append(audit_error(f"{base_path}/study/panels", "manifest panel inventory differs from authoritative PDF audit", {
                "audit": expected_labels, "manifest": actual_labels
            }))

        source_anchor_text = " ".join([
            norm(source.get("title_en")),
            norm(source.get("caption_en")),
            *(related.get(asset_id) or []),
        ])
        source_anchors = anchors(source_anchor_text)
        explicit = entry.get("panel_anchors") or {}
        for index, panel in enumerate(panels):
            label = norm(panel.get("label")) or "整图"
            panel_path = f"{base_path}/study/panels/{index}"
            explanation = norm(panel.get("explanation"))
            title = norm(panel.get("title"))
            panel_errors: list[dict[str, Any]] = []
            if not CJK.search(explanation) or len(explanation) < 80:
                panel_errors.append(audit_error(panel_path, "curated panel explanation is not substantive Chinese", len(explanation)))
            if not CJK.search(title) or len(title) < 4:
                panel_errors.append(audit_error(panel_path, "curated panel title is missing or non-specific", title))

            explanation_anchors = anchors(explanation)
            explicit_anchors = {norm(value).casefold().rstrip(".") for value in explicit.get(label) or [] if norm(value)}
            overlap = explanation_anchors & (source_anchors | explicit_anchors)
            if not overlap:
                panel_errors.append(audit_error(panel_path, "curated explanation lacks a PDF-traceable abbreviation, marker or value", {
                    "explanation_anchors": sorted(explanation_anchors),
                    "source_anchors_sample": sorted(source_anchors)[:40],
                    "audited_panel_anchors": sorted(explicit_anchors),
                }))
            if explicit_anchors and not (explanation_anchors & explicit_anchors):
                panel_errors.append(audit_error(panel_path, "curated explanation omits its audited panel anchor", sorted(explicit_anchors)))

            local_errors.extend(panel_errors)
            if not panel_errors:
                approved_panels.add(panel_path)

        errors.extend(local_errors)
        if not local_errors:
            approved_assets.add(asset_id)

    return errors, approved_assets, approved_panels


def validate(
    manifest: dict[str, Any],
    evidence: dict[str, Any],
    curated_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = v4.validate(manifest, evidence)
    if curated_audit is None:
        result["version"] = "v082-reader-semantics-5"
        result["curated_panel_audit"] = {"provided": False}
        return result

    audit_errors, approved_assets, approved_panels = validate_curated_audit(
        manifest, evidence, curated_audit
    )
    retained: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    for item in result.get("errors") or []:
        path = str(item.get("path") or "")
        issue = str(item.get("issue") or "")
        asset_id = ""
        if path.startswith("assets/"):
            parts = path.split("/")
            if len(parts) >= 2:
                asset_id = parts[1]
        filterable = False
        if issue == "panel labels/order diverge from evidence" and asset_id in approved_assets:
            filterable = True
        elif issue in {
            "panel explanation contains no traceable source entity or value",
            "generic prose is substituting for panel-specific explanation",
        }:
            panel_path = "/".join(path.split("/")[:5])
            if panel_path in approved_panels:
                filterable = True
        if filterable and issue in CURATED_FILTERABLE:
            filtered.append({**item, "resolved_by": "authoritative PDF-image curated panel audit"})
        else:
            retained.append(item)

    retained.extend(audit_errors)
    result.update({
        "version": "v082-reader-semantics-5",
        "curated_panel_audit": {
            "provided": True,
            "version": curated_audit.get("version"),
            "approved_assets": sorted(approved_assets),
            "approved_panels": len(approved_panels),
            "filtered_parser_false_positives": filtered,
            "audit_error_count": len(audit_errors),
        },
        "errors": retained,
        "passed": not retained,
    })
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate source-grounded V0.8.2 content with optional authoritative PDF-image panel audit"
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--curated-audit", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text("utf-8"))
    evidence = json.loads(args.evidence.read_text("utf-8"))
    audit = json.loads(args.curated_audit.read_text("utf-8")) if args.curated_audit else None
    result = validate(manifest, evidence, audit)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", "utf-8")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
