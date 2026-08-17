#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


RAW_INTERNAL_ID = re.compile(r"\b(?:extended-data-figure|supplementary-figure|figure|table)-\d+[a-z0-9_-]*\b", re.I)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text("utf-8"))


def extract_v6_study(html: str) -> dict[str, Any]:
    marker = "const V6_STUDY="
    start = html.find(marker)
    if start < 0:
        return {}
    start += len(marker)
    decoder = json.JSONDecoder()
    try:
        value, _ = decoder.raw_decode(html[start:])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def hidden(node) -> bool:
    if node is None:
        return True
    if node.has_attr("hidden"):
        return True
    if str(node.get("aria-hidden", "")).lower() == "true":
        return True
    style = str(node.get("style", "")).replace(" ", "").lower()
    return "display:none" in style


def validate_reader(path: Path, *, baseline_name: str | None = None) -> dict[str, Any]:
    html = path.read_text("utf-8")
    soup = BeautifulSoup(html, "html.parser")
    errors: list[str] = []
    warnings: list[str] = []

    body = soup.body
    if body is None:
        errors.append("missing <body>")
    elif body.get("data-mode") != "bilingual":
        errors.append("reader does not start in bilingual mode")

    if not hidden(soup.select_one("#quick-pane")):
        errors.append("redundant Quick Read pane is visible")
    if not hidden(soup.select_one("#readerModeSwitch")):
        errors.append("redundant reader mode switch is visible")

    sentence_nodes = soup.select(".sentence-piece[data-sentence-group]")
    if not sentence_nodes:
        errors.append("no sentence-level bilingual pieces were rendered")
    groups: dict[str, list[Any]] = defaultdict(list)
    for node in sentence_nodes:
        groups[str(node.get("data-sentence-group"))].append(node)
    for group, nodes in groups.items():
        langs = sorted(str(node.get("data-language", "")) for node in nodes)
        if len(nodes) != 2:
            errors.append(f"sentence group {group} has {len(nodes)} sides instead of exactly two")
        if langs != ["en", "zh"]:
            errors.append(f"sentence group {group} languages are {langs!r}, expected ['en', 'zh']")
        if any(not node.get_text(" ", strip=True) for node in nodes):
            errors.append(f"sentence group {group} contains an empty side")

    citations = soup.select(".citation[data-refs]")
    if not citations:
        errors.append("no interactive in-text citations were rendered")
    for node in citations:
        if node.find_parent(class_="sentence-piece") is None:
            errors.append(f"citation {node.get_text(' ', strip=True)!r} is detached from its sentence")
        refs = [item.strip() for item in str(node.get("data-refs", "")).split(",") if item.strip()]
        if not refs:
            errors.append("citation node has an empty data-refs mapping")
        for ref in refs:
            if not ref.isdigit():
                errors.append(f"citation mapping contains a non-reference token: {ref!r}")
                continue
            if soup.select_one(f"#reference-{ref}") is None:
                errors.append(f"citation points to missing reference-{ref}")

    figure_cards = soup.select(".figure-card[id]")
    if not figure_cards:
        errors.append("no populated figure cards were rendered")
    ids = [str(card.get("id")) for card in figure_cards]
    if len(ids) != len(set(ids)):
        errors.append("duplicate figure-card IDs detected")
    for card in figure_cards:
        card_id = str(card.get("id"))
        heading = card.select_one(".figure-heading")
        content = card.select_one(".figure-content")
        if heading is None or not heading.get_text(" ", strip=True):
            errors.append(f"{card_id} has an empty heading")
        if content is None or not content.get_text(" ", strip=True):
            errors.append(f"{card_id} has empty figure content")
        if card.select_one(".caption-en") is None or not card.select_one(".caption-en").get_text(" ", strip=True):
            errors.append(f"{card_id} is missing the English source caption")
        if card.select_one(".caption-zh") is None or not card.select_one(".caption-zh").get_text(" ", strip=True):
            errors.append(f"{card_id} is missing the Chinese caption")
        if card.select_one(".figure-study-button") is None:
            errors.append(f"{card_id} has no figure-study entry point")

    inline_asset_refs = [
        node for node in soup.select(".figure-ref[data-target]")
        if "v6-asset-card" not in (node.get("class") or [])
    ]
    if figure_cards and not inline_asset_refs:
        errors.append("figures exist but no inline clickable figure/table references were rendered")
    for node in inline_asset_refs:
        if node.find_parent(class_="sentence-piece") is None:
            errors.append(f"asset reference {node.get_text(' ', strip=True)!r} is detached from its sentence")
        target = str(node.get("data-target", "")).strip()
        if not target:
            errors.append("inline asset reference has an empty data-target")
        elif soup.select_one(f"#{target}") is None:
            errors.append(f"inline asset reference points to missing target {target!r}")

    term_nodes = soup.select(".term-pop[data-term-id]")
    if not term_nodes:
        errors.append("terminology interaction layer is absent")
    body_term_nodes = [node for node in term_nodes if node.find_parent(class_="sentence-piece") is not None]
    if term_nodes and not body_term_nodes:
        errors.append("terminology entries exist but none are instantiated in sentence-level body text")
    for node in body_term_nodes:
        if not str(node.get("data-tip", "")).strip():
            errors.append(f"term {node.get('data-term-id')!r} has no contextual definition")

    visible_text = soup.get_text(" ", strip=True)
    leaked_ids = sorted(set(RAW_INTERNAL_ID.findall(visible_text)))
    if leaked_ids:
        errors.append("raw internal asset IDs leaked into visible text: " + ", ".join(leaked_ids[:10]))

    study = extract_v6_study(html)
    if not study:
        errors.append("V6_STUDY figure-study data is missing or not valid JSON")
    else:
        for card_id in ids:
            data = study.get(card_id)
            if not isinstance(data, dict):
                errors.append(f"{card_id} has no figure-study data")
                continue
            overview = str(data.get("overview", "")).strip()
            conclusion = str(data.get("conclusion", "")).strip()
            panels = data.get("panels")
            if not overview:
                errors.append(f"{card_id} has an empty figure-study overview")
            if not conclusion:
                errors.append(f"{card_id} has an empty figure-study conclusion")
            if not isinstance(panels, list) or not panels:
                errors.append(f"{card_id} has no subpanel/logical-block explanations")
                continue
            seen_labels: set[str] = set()
            for index, panel in enumerate(panels, 1):
                if not isinstance(panel, dict):
                    errors.append(f"{card_id} panel {index} is not a structured object")
                    continue
                label = str(panel.get("label", "")).strip()
                title = str(panel.get("title", "")).strip()
                explanation = str(panel.get("explanation", panel.get("body", ""))).strip()
                if not label:
                    errors.append(f"{card_id} panel {index} has no label")
                elif label in seen_labels:
                    warnings.append(f"{card_id} repeats panel label {label!r}; verify that this is intentional")
                seen_labels.add(label)
                if not title:
                    errors.append(f"{card_id} panel {index} has no specific title")
                if len(explanation) < 30:
                    errors.append(f"{card_id} panel {index} explanation is too short to be a real subpanel reading")

    if baseline_name and path.name == baseline_name:
        warnings.append("reference baseline itself was validated; reference observations are informational, not universal count thresholds")

    return {
        "path": str(path),
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "sentence_piece_nodes": len(sentence_nodes),
            "sentence_groups": len(groups),
            "citations": len(citations),
            "inline_asset_refs": len(inline_asset_refs),
            "figure_cards": len(figure_cards),
            "term_highlights": len(term_nodes),
            "reference_items": len(soup.select(".reference-item[id]")),
            "figure_studies": len(study),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("readers", nargs="+", type=Path)
    parser.add_argument("--standard", type=Path, default=Path("config/v082_latest_reader_standard.json"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    standard = load_json(args.standard)
    baseline_name = str((standard.get("reference_artifact") or {}).get("filename") or "") or None
    results = [validate_reader(path, baseline_name=baseline_name) for path in args.readers]
    report = {
        "version": "v082-latest-reader-standard-gate-1",
        "standard_id": standard.get("standard_id"),
        "standard_sha256": (standard.get("reference_artifact") or {}).get("sha256"),
        "passed": all(item["passed"] for item in results),
        "readers": results,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
