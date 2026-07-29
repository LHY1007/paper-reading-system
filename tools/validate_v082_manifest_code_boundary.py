#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterator


FORBIDDEN_CODE_PATTERNS = [
    ("document shell", re.compile(r"<!doctype\b|<html\b|</html\s*>", re.I)),
    ("script", re.compile(r"<script\b|</script\s*>|javascript\s*:", re.I)),
    ("style", re.compile(r"<style\b|</style\s*>", re.I)),
    ("layout element", re.compile(r"<(?:body|head|main|aside|nav|header|footer|section|article|div)\b", re.I)),
    ("interactive element", re.compile(r"<(?:button|input|select|textarea|dialog|details|summary)\b", re.I)),
    ("event handler", re.compile(r"\bon(?:click|change|input|load|error|keydown|keyup|pointerdown|mousedown)\s*=", re.I)),
    ("CSS rule", re.compile(r"(?:^|[}\s])(?:#[A-Za-z][\w-]*|\.[A-Za-z][\w-]*)\s*\{[^{}]{0,1000}\}", re.S)),
]

ALLOWED_DATA_FIELDS = {"image_src"}


def walk(value: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in ALLOWED_DATA_FIELDS:
                continue
            yield from walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def analyze(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text("utf-8"))
    violations: list[dict[str, str]] = []
    for field, value in walk(data):
        for category, pattern in FORBIDDEN_CODE_PATTERNS:
            match = pattern.search(value)
            if match:
                start = max(0, match.start() - 60)
                end = min(len(value), match.end() + 60)
                violations.append(
                    {
                        "field": field,
                        "category": category,
                        "match": match.group(0)[:160],
                        "context": value[start:end].replace("\n", " ")[:300],
                    }
                )
    return {
        "version": "v082-manifest-code-boundary-1",
        "manifest": str(path),
        "policy": "AI and PDF extraction may provide structured paper data only; HTML, CSS, controls and interaction code belong to the frozen shell.",
        "violations": violations,
        "passed": not violations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Reject HTML, CSS and interaction code in V0.8.2 paper manifests")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = analyze(args.manifest)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", "utf-8")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
