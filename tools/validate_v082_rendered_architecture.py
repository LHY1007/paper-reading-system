#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

import validate_v082_canvas_components as component_contract
import validate_v082_canvas_shell_lock as shell_lock


DYNAMIC_ASSIGNMENTS = {
    "canvas-reader-v060-script": ["V6_ASSETS", "V6_HOTSPOTS", "V6_STUDY"],
    "canvas-reader-v061-script": ["TERM_DATA"],
    "canvas-reader-v062-script": ["KEY", "supported"],
    "canvas-v073-script": ["STORE"],
    "canvas-v077-script": ["STUDY_IDS"],
    "canvas-v078-final-script": ["TERMS"],
    "canvas-v081-script": ["EXTRA_TERMS"],
    "canvas-v082-script": ["STUDY_IDS", "ONTOLOGY"],
}

DATA_ONLY_SCRIPT_IDS = {"referenceData", "v080ReviewManifest"}

STORAGE_EXPRESSIONS = {
    "'paper-reader-canvas-v076'": "'__V082_STORAGE_V076__'",
    "'paper-reader-'+document.body.dataset.paperKey+'-v076'": "'__V082_STORAGE_V076__'",
    "'paper-reader-'+document.body.dataset.paperKey+'-v082'": "'__V082_STORAGE_V082__'",
    "'paper-reader-'+document.body.dataset.paperKey+'-v082-study'": "'__V082_STORAGE_STUDY__'",
}


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def script_text(node: Tag) -> str:
    if node.string is not None:
        return str(node.string)
    return str(node.decode_contents())


def replace_assignment(script: str, name: str, replacement: str = "__V082_DYNAMIC_DATA__") -> tuple[str, bool]:
    match = re.search(rf"\b(?:const|let|var)\s+{re.escape(name)}\s*=", script)
    if not match:
        return script, False
    pos = match.end()
    quote: str | None = None
    escaped = False
    depth = 0
    index = pos
    while index < len(script):
        char = script[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        else:
            if char in "'\"`":
                quote = char
            elif char in "([{":
                depth += 1
            elif char in ")]}":
                depth -= 1
            elif char == ";" and depth == 0:
                return script[:pos] + replacement + script[index:], True
        index += 1
    raise RuntimeError(f"unterminated JavaScript assignment for {name}")


def normalize_script(node: Tag, missing_interfaces: list[str]) -> str:
    script_id = str(node.get("id") or "")
    text = script_text(node)
    for name in DYNAMIC_ASSIGNMENTS.get(script_id, []):
        text, found = replace_assignment(text, name)
        if not found:
            missing_interfaces.append(f"{script_id}:{name}")
    for source, replacement in STORAGE_EXPRESSIONS.items():
        text = text.replace(source, replacement)
    return text


def normalized_script_inventory(soup: BeautifulSoup) -> tuple[list[dict[str, Any]], list[str]]:
    inventory: list[dict[str, Any]] = []
    missing_interfaces: list[str] = []
    for node in soup.find_all("script"):
        if node.find_parent(id="bilingual-pane") is not None:
            continue
        script_id = node.get("id")
        if script_id in DATA_ONLY_SCRIPT_IDS:
            continue
        normalized = normalize_script(node, missing_interfaces)
        inventory.append(
            {
                "index": len(inventory),
                "id": script_id,
                "type": node.get("type"),
                "src": node.get("src"),
                "sha256": sha_text(normalized),
            }
        )
    return inventory, sorted(set(missing_interfaces))


def fixed_button_inventory(soup: BeautifulSoup) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for button in soup.find_all("button"):
        if button.find_parent(id="bilingual-pane") is not None:
            continue
        attrs = {
            key: value
            for key, value in sorted(button.attrs.items())
            if key not in {"style"}
        }
        inventory.append(
            {
                "index": len(inventory),
                "attrs": attrs,
                "text": " ".join(button.get_text(" ", strip=True).split()),
            }
        )
    return inventory


def expected_counts(manifest: dict[str, Any]) -> dict[str, int]:
    sections = manifest.get("sections") or []
    assets = manifest.get("assets") or []
    paragraph_count = sum(
        1
        for section in sections
        for block in section.get("blocks") or []
        if block.get("type") == "paragraph"
    )
    asset_block_count = sum(
        1
        for section in sections
        for block in section.get("blocks") or []
        if block.get("type") == "asset"
    )
    return {
        "paper_sections": len(sections) + 1,
        "bilingual_units": paragraph_count,
        "figure_cards": sum(asset.get("kind") == "figure" for asset in assets),
        "table_cards": sum(asset.get("kind") == "table" for asset in assets),
        "references": len(manifest.get("references") or []),
        "figure_index_buttons": asset_block_count,
        "study_buttons": sum(asset.get("kind") == "figure" and bool(asset.get("study")) for asset in assets),
    }


def actual_counts(soup: BeautifulSoup) -> dict[str, int]:
    return {
        "paper_sections": len(soup.select("#bilingual-pane > section.paper-section")),
        "bilingual_units": len(soup.select("#bilingual-pane .bilingual-unit")),
        "figure_cards": len(soup.select("#bilingual-pane .figure-card:not(.table-card)")),
        "table_cards": len(soup.select("#bilingual-pane .table-card")),
        "references": len(soup.select("#references > .reference-item")),
        "figure_index_buttons": len(soup.select("#figure-table-index .figure-ref")),
        "study_buttons": len(soup.select("#bilingual-pane .figure-study-button")),
    }


def analyze(shell: Path, rendered: Path, manifest_path: Path, lock_path: Path) -> dict[str, Any]:
    shell_raw = shell.read_text("utf-8")
    rendered_raw = rendered.read_text("utf-8")
    shell_soup = BeautifulSoup(shell_raw, "html.parser")
    rendered_soup = BeautifulSoup(rendered_raw, "html.parser")
    manifest = json.loads(manifest_path.read_text("utf-8"))
    lock = json.loads(lock_path.read_text("utf-8"))
    errors: list[Any] = []

    shell_sha = sha_file(shell)
    if shell_sha != lock.get("frozen_shell_sha256") or shell.stat().st_size != lock.get("frozen_shell_bytes"):
        errors.append(
            {
                "shell_lock_mismatch": {
                    "expected_sha256": lock.get("frozen_shell_sha256"),
                    "actual_sha256": shell_sha,
                    "expected_bytes": lock.get("frozen_shell_bytes"),
                    "actual_bytes": shell.stat().st_size,
                }
            }
        )

    rendered_html = rendered_soup.find("html")
    provenance = {
        "template": rendered_html.get("data-v082-template") if rendered_html else None,
        "shell_sha256": rendered_html.get("data-v082-shell-sha256") if rendered_html else None,
        "shell_lock": rendered_html.get("data-v082-shell-lock") if rendered_html else None,
    }
    expected_provenance = {
        "template": "frozen-shell-rendered",
        "shell_sha256": shell_sha,
        "shell_lock": lock.get("version"),
    }
    if provenance != expected_provenance:
        errors.append({"render_provenance_mismatch": {"expected": expected_provenance, "actual": provenance}})

    shell_norm, shell_meta = shell_lock.neutralize(shell)
    rendered_norm, rendered_meta = shell_lock.neutralize(rendered)
    global_shell_hashes = {
        "shell": sha_text(shell_norm),
        "rendered": sha_text(rendered_norm),
    }
    if global_shell_hashes["shell"] != global_shell_hashes["rendered"]:
        errors.append("fixed global DOM shell changed during rendering")
    if shell_meta.get("errors"):
        errors.append({"shell_neutralization_errors": shell_meta["errors"]})
    if rendered_meta.get("errors"):
        errors.append({"rendered_neutralization_errors": rendered_meta["errors"]})

    shell_styles = shell_lock.core.style_hashes(shell_soup)
    rendered_styles = shell_lock.core.style_hashes(rendered_soup)
    if shell_styles != rendered_styles:
        errors.append("style blocks changed during rendering")

    shell_scripts, shell_missing = normalized_script_inventory(shell_soup)
    rendered_scripts, rendered_missing = normalized_script_inventory(rendered_soup)
    if shell_missing or rendered_missing:
        errors.append({"missing_dynamic_script_interfaces": {"shell": shell_missing, "rendered": rendered_missing}})
    if shell_scripts != rendered_scripts:
        errors.append("static JavaScript skeleton changed during rendering")

    shell_buttons = fixed_button_inventory(shell_soup)
    rendered_buttons = fixed_button_inventory(rendered_soup)
    if shell_buttons != rendered_buttons:
        errors.append("fixed global button inventory changed during rendering")

    component_report = component_contract.validate(rendered)
    if not component_report.get("passed"):
        errors.append({"component_contract": component_report.get("errors") or []})

    expected = expected_counts(manifest)
    actual = actual_counts(rendered_soup)
    if expected != actual:
        errors.append({"manifest_component_count_mismatch": {"expected": expected, "actual": actual}})

    return {
        "version": "v082-rendered-architecture-gate-1",
        "shell": str(shell),
        "shell_sha256": shell_sha,
        "shell_lock": str(lock_path),
        "shell_lock_version": lock.get("version"),
        "manifest": str(manifest_path),
        "manifest_sha256": sha_file(manifest_path),
        "rendered": str(rendered),
        "rendered_sha256": sha_file(rendered),
        "provenance": provenance,
        "global_shell_hashes": global_shell_hashes,
        "style_hashes": rendered_styles,
        "normalized_script_inventory": rendered_scripts,
        "fixed_global_button_count": len(rendered_buttons),
        "fixed_global_button_sha256": sha_text(json.dumps(rendered_buttons, ensure_ascii=False, sort_keys=True)),
        "expected_counts": expected,
        "actual_counts": actual,
        "component_contract": component_report,
        "errors": errors,
        "passed": not errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify that a rendered V0.8.2 paper changes data only and preserves the fixed CANVAS product architecture")
    parser.add_argument("rendered", type=Path)
    parser.add_argument("--shell", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=Path("config/v082_frozen_shell_lock.json"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = analyze(args.shell, args.rendered, args.manifest, args.lock)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", "utf-8")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
