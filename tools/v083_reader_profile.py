#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def load_config(path: Path | str = Path("config/v083_reader_profiles.json")) -> dict[str, Any]:
    return json.loads(Path(path).read_text("utf-8"))


def flatten_source_text(raw: dict[str, Any]) -> str:
    parts: list[str] = []
    paper = raw.get("paper") or {}
    parts.extend([paper.get("title_en"), paper.get("journal"), paper.get("article_type")])
    for section in raw.get("sections", []):
        parts.extend([section.get("title_en"), section.get("title_zh")])
        for block in section.get("blocks", []):
            if block.get("type") != "paragraph":
                continue
            parts.extend(item.get("text") for item in block.get("english", []))
    return " ".join(norm(value) for value in parts if norm(value))


def manual_profile(plan: dict[str, Any] | None) -> str | None:
    if not plan:
        return None
    value = plan.get("reader_profile")
    if isinstance(value, dict):
        value = value.get("name")
    value = norm(value).lower()
    return value if value in {"standard", "figure_intensive"} else None


def classify(
    raw: dict[str, Any],
    plan: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = config or load_config()
    override = manual_profile(plan)
    profiles = config["profiles"]
    if override:
        return {
            "name": override,
            "figure_study_enabled": bool(profiles[override]["figure_study_enabled"]),
            "decision": "manual_override",
            "signals": [f"paper plan explicitly selected {override}"],
        }

    paper = raw.get("paper") or {}
    journal = norm(paper.get("journal"))
    corpus = flatten_source_text(raw).lower()
    rules = config["automatic_rules"]
    signals: list[str] = []

    cns = False
    for pattern in rules.get("cns_journal_patterns", []):
        if re.search(pattern, journal, re.I):
            cns = True
            signals.append(f"CNS-family journal signal: {journal}")
            break

    strong_hits = [
        keyword for keyword in rules.get("strong_single_keyword_triggers", [])
        if keyword.lower() in corpus
    ]
    keyword_hits = [
        keyword for keyword in rules.get("bioinformatics_keywords", [])
        if keyword.lower() in corpus
    ]
    bioinformatics = bool(strong_hits) or len(keyword_hits) >= int(rules.get("bioinformatics_keyword_threshold", 2))
    if strong_hits:
        signals.append("strong biology/bioinformatics signal: " + ", ".join(strong_hits[:6]))
    elif bioinformatics:
        signals.append("biology/bioinformatics keyword signals: " + ", ".join(keyword_hits[:8]))

    if cns or bioinformatics:
        name = "figure_intensive"
        decision = "automatic_figure_intensive"
    else:
        name = config.get("default_profile", "standard")
        decision = "automatic_standard"
        if any(re.search(pattern, journal, re.I) for pattern in rules.get("engineering_journal_patterns", [])):
            signals.append(f"conventional engineering/method journal signal: {journal}")
        if not signals:
            signals.append("no CNS-family or biology/bioinformatics-heavy signal")

    return {
        "name": name,
        "figure_study_enabled": bool(profiles[name]["figure_study_enabled"]),
        "decision": decision,
        "signals": signals,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify the V0.8.3 reader profile for one paper")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--config", type=Path, default=Path("config/v083_reader_profiles.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    raw = json.loads(args.manifest.read_text("utf-8"))
    plan = json.loads(args.plan.read_text("utf-8")) if args.plan and args.plan.exists() else None
    result = classify(raw, plan=plan, config=load_config(args.config))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", "utf-8")


if __name__ == "__main__":
    main()
