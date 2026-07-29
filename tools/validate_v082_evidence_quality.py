#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


GENERIC_FIGURE = re.compile(r"^(?:Fig\.?|Figure\s+[A-Za-z]?\d+\.?|Extended Data Figure\s+\d+\.?)$", re.I)
PARSER_VERSION = re.compile(r"^v082-final-(?:[6-9]|[1-9]\d+)$")
CONTAMINATION = re.compile(
    r"(?:Nature Genetics|Nature Medicine|Nature Machine Intelligence|Nature Communications|Cell)\s*(?:\||\d)|Article\s+https?://|Received:\s+\d|Accepted:\s+\d|legend continued on next page",
    re.I,
)


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def add(errors: list[dict[str, Any]], path: str, issue: str, value: Any = None) -> None:
    item: dict[str, Any] = {"path": path, "issue": issue}
    if value is not None:
        item["value"] = norm(value)[:600]
    errors.append(item)


def validate(manifest: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    parser_version = norm(audit.get("strict_layout_parser"))
    if not PARSER_VERSION.fullmatch(parser_version):
        add(errors, "audit.strict_layout_parser", "parser v6 or newer is required", parser_version)
    if not audit.get("passed"):
        add(errors, "audit.passed", "source extraction audit did not pass")
    if audit.get("strict_errors"):
        add(errors, "audit.strict_errors", "strict extraction errors remain", audit.get("strict_errors"))
    if int(audit.get("formula_blocks_missing", -1)) != 0:
        add(errors, "audit.formula_blocks_missing", "standalone formula evidence was lost", audit.get("formula_blocks_missing"))

    outline = manifest.get("evidence_outline") or []
    scientific_outline = [
        item
        for item in outline
        if item.get("kind") == "section"
        and norm(item.get("title")).lower() not in {"article", "check for updates", "online content"}
    ]
    if len(scientific_outline) < 5:
        add(errors, "evidence_outline", "PDF outline does not contain enough scientific sections", len(scientific_outline))
    if not any(norm(item.get("title")).lower() == "results" for item in scientific_outline):
        add(errors, "evidence_outline", "Results section is missing from source outline")

    assets = manifest.get("assets") or []
    figure_count = 0
    table_count = 0
    generic_titles: list[str] = []
    contaminated_captions: list[str] = []
    panel_evidence_missing: list[str] = []
    table_failures: list[str] = []
    image_missing: list[str] = []
    for index, asset in enumerate(assets):
        asset_id = norm(asset.get("id")) or f"asset-{index}"
        kind = asset.get("kind")
        title = norm(asset.get("title_en"))
        caption = norm(asset.get("caption_en"))
        if kind == "figure":
            figure_count += 1
            if title.lower() != "graphical abstract" and GENERIC_FIGURE.fullmatch(title):
                generic_titles.append(asset_id)
            if not asset.get("image_src"):
                image_missing.append(asset_id)
            if len(caption) > 5000 or CONTAMINATION.search(caption):
                contaminated_captions.append(asset_id)
            study = asset.get("study") or {}
            panels = study.get("panels") or []
            if re.search(r"\([A-Za-z](?:\s*(?:and|,|–|-)\s*[A-Za-z])?\)", caption) and not panels:
                panel_evidence_missing.append(asset_id)
        elif kind == "table":
            table_count += 1
            table = asset.get("table") or {}
            headers = table.get("headers") or []
            rows = table.get("rows") or []
            if not headers or not rows or any(len(row) != len(headers) for row in rows):
                table_failures.append(asset_id)
        else:
            add(errors, f"assets[{index}].kind", "asset kind must be figure or table", kind)
        if title.lower().startswith("table") and kind != "table":
            table_failures.append(asset_id)

    if not assets:
        add(errors, "assets", "no source figures or tables were extracted")
    if generic_titles:
        add(errors, "assets.title_en", "descriptive figure titles were not recovered", generic_titles)
    if contaminated_captions:
        add(errors, "assets.caption_en", "caption contains running header, continuation marker or adjacent body text", contaminated_captions)
    if panel_evidence_missing:
        add(errors, "assets.study.panels", "caption panel labels exist but no source panel evidence was extracted", panel_evidence_missing)
    if table_failures:
        add(errors, "assets.table", "source table was not reconstructed as aligned headers and rows", sorted(set(table_failures)))
    if image_missing:
        add(errors, "assets.image_src", "source figure image is missing", image_missing)

    references = manifest.get("references") or []
    reference_ids = [str(item.get("id", "")) for item in references]
    expected_count = int(audit.get("expected_reference_count", 0) or 0)
    if expected_count and len(references) != expected_count:
        add(errors, "references", "reference count differs from registered source", {"actual": len(references), "expected": expected_count})
    expected_ids = [str(index) for index in range(1, len(references) + 1)]
    if reference_ids != expected_ids:
        add(errors, "references.id", "original continuous source numbering was not preserved", reference_ids)
    implausible_refs: list[str] = []
    for item in references:
        text = norm(item.get("text"))
        if len(text) < 30 or not re.search(r"\b(?:19|20)\d{2}\b", text):
            implausible_refs.append(str(item.get("id")))
    if implausible_refs:
        add(errors, "references.text", "entries do not resemble complete bibliographic records", implausible_refs[:30])

    repairs = manifest.get("evidence_repairs") or {}
    if int(repairs.get("reference_count", len(references)) or 0) != len(references):
        add(errors, "evidence_repairs.reference_count", "repair report is inconsistent with manifest references")
    continuation_missing = [str(value) for value in repairs.get("continuation_blocks_missing") or []]
    if continuation_missing:
        add(errors, "evidence_repairs.continuation_blocks_missing", "cross-page figure legend continuation was not recovered", continuation_missing)
    if table_count and int(repairs.get("tables_reconstructed", 0) or 0) < table_count:
        warnings.append({"path": "evidence_repairs.tables_reconstructed", "issue": "not every table reports native reconstruction"})

    return {
        "version": "v082-evidence-quality-2",
        "paper_key": manifest.get("paper", {}).get("key"),
        "parser": parser_version,
        "outline_entries": len(outline),
        "scientific_outline_entries": len(scientific_outline),
        "figures": figure_count,
        "tables": table_count,
        "references": len(references),
        "expected_references": expected_count,
        "errors": errors,
        "warnings": warnings,
        "passed": not errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate PDF evidence before reader-content generation")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = validate(json.loads(args.manifest.read_text("utf-8")), json.loads(args.audit.read_text("utf-8")))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
