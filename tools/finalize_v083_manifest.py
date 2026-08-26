#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from v083_reader_profile import classify, load_config


BRACKET_CITATION_RE = re.compile(r"\[(?P<body>\d{1,3}(?:\s*[-–,]\s*\d{1,3})*)\]")
FIG_REF_RE = re.compile(
    r"\b(?P<label>Figure|Fig\.|Extended Data Fig\.|Supplementary Fig\.|Supplementary Figure|Table|Extended Data Table|Supplementary Table)\s+(?P<num>[A-Z]?\d+[A-Za-z]?)",
    re.I,
)
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
ARXIV_RE = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
URL_RE = re.compile(r"https?://\S+")
QUOTED_TITLE_RE = re.compile(r"[“\"]([^”\"]{12,240})[”\"]")
CJK_RE = re.compile(r"[\u3400-\u9fff]")


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def citation_ids(body: str) -> list[str]:
    values: list[str] = []
    for token in re.split(r"\s*,\s*", body):
        m = re.fullmatch(r"(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?", token)
        if not m:
            continue
        start = int(m.group(1)); end = int(m.group(2) or start)
        if start > end or end - start > 100:
            continue
        for number in range(start, end + 1):
            value = str(number)
            if value not in values:
                values.append(value)
    return values


def split_bracket_citations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parsed_ids: set[str] = set()
    output: list[dict[str, Any]] = []
    found = False
    for item in items:
        text = str(item.get("text") or "")
        if not text or item.get("citation_label"):
            output.append(dict(item))
            continue
        cursor = 0
        matches = list(BRACKET_CITATION_RE.finditer(text))
        if not matches:
            output.append(dict(item))
            continue
        found = True
        for match in matches:
            if match.start() > cursor:
                left = dict(item)
                left["text"] = text[cursor:match.start()]
                left.pop("citation_ids", None)
                output.append(left)
            ids = citation_ids(match.group("body"))
            if ids:
                parsed_ids.update(ids)
                output.append({
                    "text": "",
                    "citation_ids": ids,
                    "citation_label": match.group(0),
                })
            else:
                output.append({"text": match.group(0)})
            cursor = match.end()
        if cursor < len(text):
            right = dict(item)
            right["text"] = text[cursor:]
            right.pop("citation_ids", None)
            output.append(right)
    if found and parsed_ids:
        # PDF-native IEEE/engineering citations are already present in the source text.
        # Remove duplicate paragraph-end citation metadata for IDs that were restored
        # at their exact source position above.
        for item in output:
            if item.get("citation_label"):
                continue
            ids = [str(value) for value in item.get("citation_ids", []) if str(value) not in parsed_ids]
            if ids:
                item["citation_ids"] = ids
            else:
                item.pop("citation_ids", None)
    return [item for item in output if item.get("text") or item.get("citation_ids") or item.get("figure_ids") or item.get("term_id") or item.get("section_id")]


def asset_id(label: str, number: str) -> str:
    key = label.lower().replace(".", "")
    key = key.replace("supplementary figure", "supplementary-figure").replace("supplementary fig", "supplementary-figure")
    key = key.replace("extended data figure", "extended-data-figure").replace("extended data fig", "extended-data-figure")
    key = key.replace("extended data table", "extended-data-table").replace(" ", "-")
    if key == "fig":
        key = "figure"
    return f"{key}-{number.lower()}"


def split_figure_refs(items: list[dict[str, Any]], known_assets: set[str]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in items:
        if item.get("citation_label") or item.get("figure_ids") or item.get("section_id"):
            output.append(item)
            continue
        text = str(item.get("text") or "")
        if not text:
            output.append(item)
            continue
        cursor = 0
        matches = list(FIG_REF_RE.finditer(text))
        if not matches:
            output.append(item)
            continue
        for match in matches:
            if match.start() > cursor:
                left = dict(item)
                left["text"] = text[cursor:match.start()]
                output.append(left)
            aid = asset_id(match.group("label"), match.group("num"))
            middle = dict(item)
            middle["text"] = match.group(0)
            if aid in known_assets:
                middle["figure_ids"] = [aid]
            output.append(middle)
            cursor = match.end()
        if cursor < len(text):
            right = dict(item)
            right["text"] = text[cursor:]
            output.append(right)
    return [item for item in output if item.get("text") or item.get("citation_ids") or item.get("figure_ids") or item.get("term_id") or item.get("section_id")]


def term_aliases(terms: list[dict[str, Any]], language: str) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for term in terms:
        term_id = str(term.get("id") or "")
        aliases: list[str] = []
        if language == "en":
            aliases.extend([term.get("label"), *(term.get("aliases") or [])])
        else:
            aliases.extend([term.get("label_zh"), *(term.get("aliases_zh") or [])])
            aliases.extend(alias for alias in [term.get("label"), *(term.get("aliases") or [])] if alias and (CJK_RE.search(str(alias)) or len(str(alias)) <= 12))
        for alias in aliases:
            alias = norm(alias)
            if not term_id or len(alias) < 2:
                continue
            key = (alias.casefold(), term_id)
            if key in seen:
                continue
            seen.add(key)
            values.append((alias, term_id))
    values.sort(key=lambda value: len(value[0]), reverse=True)
    return values


def alias_matches(text: str, aliases: list[tuple[str, str]]) -> list[tuple[int, int, str]]:
    candidates: list[tuple[int, int, str]] = []
    lower = text.casefold()
    for alias, term_id in aliases:
        needle = alias.casefold()
        start = 0
        while True:
            index = lower.find(needle, start)
            if index < 0:
                break
            end = index + len(alias)
            if alias[0].isascii() and alias[0].isalnum():
                before = text[index - 1] if index else " "
                after = text[end] if end < len(text) else " "
                if before.isalnum() or before == "_" or after.isalnum() or after == "_":
                    start = index + 1
                    continue
            candidates.append((index, end, term_id))
            start = end
    candidates.sort(key=lambda value: (value[0], -(value[1] - value[0])))
    chosen: list[tuple[int, int, str]] = []
    occupied_end = -1
    for candidate in candidates:
        if candidate[0] < occupied_end:
            continue
        chosen.append(candidate)
        occupied_end = candidate[1]
    return chosen


def split_terms(items: list[dict[str, Any]], terms: list[dict[str, Any]], language: str) -> list[dict[str, Any]]:
    aliases = term_aliases(terms, language)
    if not aliases:
        return items
    output: list[dict[str, Any]] = []
    for item in items:
        if item.get("term_id") or item.get("citation_label") or item.get("figure_ids") or item.get("section_id"):
            output.append(item)
            continue
        text = str(item.get("text") or "")
        matches = alias_matches(text, aliases)
        if not matches:
            output.append(item)
            continue
        cursor = 0
        for start, end, term_id in matches:
            if start > cursor:
                left = dict(item); left["text"] = text[cursor:start]; output.append(left)
            middle = dict(item); middle["text"] = text[start:end]; middle["term_id"] = term_id; output.append(middle)
            cursor = end
        if cursor < len(text):
            right = dict(item); right["text"] = text[cursor:]; output.append(right)
    return [item for item in output if item.get("text") or item.get("citation_ids") or item.get("figure_ids") or item.get("term_id") or item.get("section_id")]


def inferred_reference_url(text: str) -> str | None:
    doi = DOI_RE.search(text)
    if doi:
        return "https://doi.org/" + doi.group(0).rstrip(".,;)")
    arxiv = ARXIV_RE.search(text)
    if arxiv:
        return "https://arxiv.org/abs/" + arxiv.group(1)
    url = URL_RE.search(text)
    if url:
        return url.group(0).rstrip(".,;)")
    title = QUOTED_TITLE_RE.search(text)
    if title:
        return "https://scholar.google.com/scholar?q=" + quote_plus(title.group(1))
    return None


def finalize(manifest: dict[str, Any], evidence: dict[str, Any] | None, plan: dict[str, Any] | None, profile_config: dict[str, Any]) -> dict[str, Any]:
    basis = evidence or manifest
    profile = classify(basis, plan=plan, config=profile_config)
    manifest["reader_profile"] = profile
    if not profile["figure_study_enabled"]:
        for asset in manifest.get("assets", []):
            asset.pop("study", None)

    known_assets = {str(asset.get("id")) for asset in manifest.get("assets", []) if asset.get("id")}
    terms = manifest.get("terms", [])
    for section in manifest.get("sections", []):
        for block in section.get("blocks", []):
            if block.get("type") != "paragraph":
                continue
            english = split_bracket_citations([dict(item) for item in block.get("english", [])])
            chinese = split_bracket_citations([dict(item) for item in block.get("chinese", [])])
            english = split_figure_refs(english, known_assets)
            chinese = split_figure_refs(chinese, known_assets)
            block["english"] = split_terms(english, terms, "en")
            block["chinese"] = split_terms(chinese, terms, "zh")

    for reference in manifest.get("references", []):
        if not norm(reference.get("url")):
            url = inferred_reference_url(norm(reference.get("text")))
            if url:
                reference["url"] = url
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply deterministic V0.8.3 profile, inline citation/figure links, term highlighting and reference links without rewriting source/translation text")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--profile-config", type=Path, default=Path("config/v083_reader_profiles.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text("utf-8"))
    evidence = json.loads(args.evidence.read_text("utf-8")) if args.evidence and args.evidence.exists() else None
    plan = json.loads(args.plan.read_text("utf-8")) if args.plan and args.plan.exists() else None
    updated = finalize(manifest, evidence, plan, load_config(args.profile_config))
    target = args.output or args.manifest
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({
        "manifest": str(target),
        "reader_profile": updated.get("reader_profile"),
        "terms": len(updated.get("terms", [])),
        "references": len(updated.get("references", [])),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
