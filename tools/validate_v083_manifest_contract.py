#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from finalize_v083_manifest import BRACKET_CITATION_RE, FIG_REF_RE, asset_id, norm


def inline_text(items: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in items:
        text = str(item.get("text") or "")
        if text:
            parts.append(text)
        label = str(item.get("citation_label") or "")
        if label:
            parts.append(label)
    return "".join(parts)


def strip_citation_markers(text: str) -> str:
    return norm(BRACKET_CITATION_RE.sub(" ", text))


def alias_expected(text: str, terms: list[dict[str, Any]], language: str) -> int:
    lower = text.casefold()
    seen_spans: set[tuple[int, int]] = set()
    aliases: list[str] = []
    for term in terms:
        if language == "en":
            values = [term.get("label"), *(term.get("aliases") or [])]
        else:
            values = [term.get("label_zh"), *(term.get("aliases_zh") or [])]
            values += [value for value in [term.get("label"), *(term.get("aliases") or [])] if value and re.search(r"[\u3400-\u9fff]", str(value))]
        aliases.extend(norm(value) for value in values if norm(value))
    for alias in sorted(set(aliases), key=len, reverse=True):
        needle = alias.casefold()
        start = 0
        while True:
            index = lower.find(needle, start)
            if index < 0:
                break
            span = (index, index + len(alias))
            if not any(not (span[1] <= old[0] or span[0] >= old[1]) for old in seen_spans):
                seen_spans.add(span)
            start = index + max(1, len(alias))
    return len(seen_spans)


def validate(manifest: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    profile = manifest.get("reader_profile") or {}
    profile_name = str(profile.get("name") or "")
    study_enabled = profile.get("figure_study_enabled")
    if profile_name not in {"standard", "figure_intensive"}:
        errors.append("reader_profile.name must be standard or figure_intensive")
    if not isinstance(study_enabled, bool):
        errors.append("reader_profile.figure_study_enabled must be boolean")

    assets = {str(asset.get("id")): asset for asset in manifest.get("assets", []) if asset.get("id")}
    references = {str(ref.get("id")): ref for ref in manifest.get("references", []) if ref.get("id")}
    terms = manifest.get("terms", [])
    cited_ids: set[str] = set()
    english_term_nodes = 0
    chinese_term_nodes = 0
    expected_en_terms = 0
    expected_zh_terms = 0
    bracket_groups = 0
    positional_bracket_groups = 0
    figure_mentions = 0
    linked_figure_mentions = 0
    paragraph_count = 0

    for section in manifest.get("sections", []):
        for block in section.get("blocks", []):
            if block.get("type") != "paragraph":
                continue
            paragraph_count += 1
            english = block.get("english", [])
            chinese = block.get("chinese", [])
            source = norm(" ".join(str(value) for value in block.get("source_fragments", [])))
            en_visible = inline_text(english)
            zh_visible = inline_text(chinese)
            if source and strip_citation_markers(source) != strip_citation_markers(en_visible):
                errors.append(f"{block.get('id')}: English reader text does not reconstruct the source paragraph exactly")

            expected_en_terms += alias_expected(en_visible, terms, "en")
            expected_zh_terms += alias_expected(zh_visible, terms, "zh")
            english_term_nodes += sum(1 for item in english if item.get("term_id"))
            chinese_term_nodes += sum(1 for item in chinese if item.get("term_id"))

            source_brackets = list(BRACKET_CITATION_RE.finditer(source))
            bracket_groups += len(source_brackets)
            labels = [str(item.get("citation_label") or "") for item in english if item.get("citation_ids")]
            positional_bracket_groups += sum(1 for match in source_brackets if match.group(0) in labels)

            citation_positions = []
            for idx, item in enumerate(english):
                ids = [str(value) for value in item.get("citation_ids", [])]
                if ids:
                    citation_positions.append(idx)
                    cited_ids.update(ids)
                    for ref_id in ids:
                        if ref_id not in references:
                            errors.append(f"{block.get('id')}: citation {ref_id} has no reference target")
            if len(citation_positions) >= 2 and len(set(citation_positions)) == 1 and citation_positions[0] == len(english) - 1:
                errors.append(f"{block.get('id')}: multiple citation groups were collapsed to the paragraph end")

            for match in FIG_REF_RE.finditer(en_visible):
                aid = asset_id(match.group("label"), match.group("num"))
                if aid not in assets:
                    continue
                figure_mentions += 1
                if any(aid in [str(value) for value in item.get("figure_ids", [])] and match.group(0) in str(item.get("text") or "") for item in english):
                    linked_figure_mentions += 1
                else:
                    errors.append(f"{block.get('id')}: {match.group(0)} is not linked at its original text position")

    if bracket_groups and positional_bracket_groups != bracket_groups:
        errors.append(f"only {positional_bracket_groups}/{bracket_groups} bracketed citation groups were restored at their original positions")

    if expected_en_terms and english_term_nodes == 0:
        errors.append("English terminology aliases occur in the body but no English term highlights were emitted")
    elif expected_en_terms and english_term_nodes / expected_en_terms < 0.65:
        errors.append(f"English term highlighting coverage is too low: {english_term_nodes}/{expected_en_terms}")
    if expected_zh_terms and chinese_term_nodes == 0:
        errors.append("Chinese terminology aliases occur in the translation but no Chinese term highlights were emitted")

    for ref_id in sorted(cited_ids, key=lambda value: int(value) if value.isdigit() else value):
        ref = references.get(ref_id) or {}
        if not norm(ref.get("url")):
            errors.append(f"cited reference {ref_id} has no external link")

    figure_assets = [asset for asset in assets.values() if asset.get("kind") == "figure"]
    studies = [asset for asset in figure_assets if asset.get("study")]
    if study_enabled is False and studies:
        errors.append("standard reader profile must not contain figure-study payloads")
    if study_enabled is True:
        missing = [str(asset.get("id")) for asset in figure_assets if not asset.get("study")]
        if missing:
            errors.append("figure_intensive profile is missing figure-study payloads for: " + ", ".join(missing[:20]))

    if paragraph_count and not cited_ids and any(BRACKET_CITATION_RE.search(norm(" ".join(str(v) for v in block.get("source_fragments", [])))) for section in manifest.get("sections", []) for block in section.get("blocks", []) if block.get("type") == "paragraph"):
        errors.append("source contains citations but manifest has no clickable citation nodes")

    return {
        "version": "v083-manifest-contract-1",
        "paper_key": (manifest.get("paper") or {}).get("key"),
        "reader_profile": profile,
        "paragraphs": paragraph_count,
        "terms": {
            "dictionary": len(terms),
            "expected_english_alias_hits": expected_en_terms,
            "english_highlight_nodes": english_term_nodes,
            "expected_chinese_alias_hits": expected_zh_terms,
            "chinese_highlight_nodes": chinese_term_nodes,
        },
        "citations": {
            "source_bracket_groups": bracket_groups,
            "positionally_restored_bracket_groups": positional_bracket_groups,
            "cited_reference_ids": len(cited_ids),
        },
        "figure_table_links": {
            "source_mentions_with_known_assets": figure_mentions,
            "positionally_linked_mentions": linked_figure_mentions,
        },
        "figure_studies": len(studies),
        "warnings": warnings,
        "errors": errors,
        "passed": not errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate V0.8.3 source fidelity, inline terminology/citations/asset links and conditional figure-study profile")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = validate(json.loads(args.manifest.read_text("utf-8")))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", "utf-8")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
