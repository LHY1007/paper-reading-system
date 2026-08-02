#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

ASSIGN_PATTERNS = [
    r"(?:window\.)?([A-Za-z_$][\w$]*)\s*=\s*(?:\{|\[|JSON\.parse)",
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=",
]

KEYWORDS = [
    "figure", "table", "caption", "reference", "citation", "bilingual",
    "translation", "section", "paper", "term", "annotation", "viewer",
    "study", "asset", "toc", "quick", "overview", "canvas"
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("html", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    raw = args.html.read_text("utf-8")
    soup = BeautifulSoup(raw, "html.parser")
    rows = []
    for index, tag in enumerate(soup.find_all("script")):
        text = tag.get_text() or ""
        assigns = []
        for pattern in ASSIGN_PATTERNS:
            assigns.extend(re.findall(pattern, text))
        preview = " ".join(text.strip().split())[:500]
        rows.append({
            "index": index,
            "id": tag.get("id"),
            "type": tag.get("type"),
            "src": tag.get("src"),
            "chars": len(text),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "assignments": sorted(set(assigns))[:100],
            "keywords": {k: len(re.findall(k, text, re.I)) for k in KEYWORDS if re.search(k, text, re.I)},
            "preview": preview,
        })
    report = {
        "file": args.html.name,
        "scripts": rows,
        "id_scripts": [r for r in rows if r["id"]],
        "large_scripts": [r for r in rows if r["chars"] >= 10000],
        "data_candidates": [
            r for r in rows
            if r["type"] == "application/json"
            or any(x.lower().endswith(("data", "registry", "manifest", "map")) for x in r["assignments"])
            or (r["chars"] >= 2000 and not re.search(r"addEventListener|querySelector|function\s*\(|=>", r["preview"]))
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
