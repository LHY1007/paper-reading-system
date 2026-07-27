#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re, subprocess, tempfile
from pathlib import Path
from bs4 import BeautifulSoup


def load_registry(text: str, name: str) -> dict:
    match = re.search(rf"window\.{name}=(\{{.*?\}});window\.", text, re.S)
    if not match:
        raise ValueError(f"missing {name}")
    return json.loads(match.group(1))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("html", type=Path)
    parser.add_argument("--expected-paragraphs", type=int)
    parser.add_argument("--expected-assets", type=int)
    args = parser.parse_args()
    raw = args.html.read_text("utf-8")
    soup = BeautifulSoup(raw, "html.parser")
    errors: list[str] = []
    assets = load_registry(raw, "READER_ASSETS")
    paragraphs = soup.select(".para-card")
    cards = {card.get("data-id"): card for card in soup.select(".asset-card[data-id]")}
    if args.expected_paragraphs is not None and len(paragraphs) != args.expected_paragraphs:
        errors.append("paragraph count mismatch")
    if args.expected_assets is not None and len(assets) != args.expected_assets:
        errors.append("asset count mismatch")
    if len(cards) != len(assets):
        errors.append("asset card count mismatch")
    if len(soup.select("#notes .note")):
        errors.append("preloaded annotation detected")
    for forbidden in ('id="quick"', 'id="evidence"', 'inline-note', '证据审查'):
        if forbidden in raw:
            errors.append("forbidden legacy feature: " + forbidden)
    for asset_id, asset in assets.items():
        card = cards.get(asset_id)
        if card is None:
            errors.append(asset_id + ": missing card")
            continue
        if card.select_one(f'[data-action="right"][data-id="{asset_id}"]') is None:
            errors.append(asset_id + ": missing right action")
        expected_study = bool(asset.get("study")) and asset.get("kind") != "table"
        actual_study = card.select_one(f'[data-action="study"][data-id="{asset_id}"]') is not None
        if expected_study != actual_study:
            errors.append(asset_id + ": study action mismatch")
        if asset.get("src") and asset["src"] not in raw:
            errors.append(asset_id + ": image data not locked")
    scripts = "\n".join(tag.get_text() for tag in soup.find_all("script"))
    required = {
        "semantic right dispatch": "if(a==='right')openRight(id)",
        "semantic study dispatch": "if(a==='study')openStudy(id)",
        "table study guard": "a.kind==='table'",
        "captions default open": "en.open=true",
        "independent Chinese caption": "zh.open=true",
        "longest alias priority": "sort((a,b)=>b.length-a.length)",
        "strict token boundary": "/[A-Za-z0-9]/.test(before)",
        "combined text annotation": "highlightBtn",
        "combined drawing annotation": "drawBtn",
        "runtime contract": "window.__READER_V082_REVIEW__",
    }
    for label, token in required.items():
        if token not in scripts:
            errors.append("missing " + label)
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(scripts)
        js_path = Path(handle.name)
    result = subprocess.run(["node", "--check", str(js_path)], capture_output=True, text=True)
    js_path.unlink(missing_ok=True)
    if result.returncode:
        errors.append("JavaScript syntax failure")
    report = {
        "passed": not errors,
        "file": args.html.name,
        "sha256": hashlib.sha256(args.html.read_bytes()).hexdigest(),
        "paragraphs": len(paragraphs),
        "assets": len(assets),
        "study_assets": sum(bool(a.get("study")) and a.get("kind") != "table" for a in assets.values()),
        "citations": len(soup.select("sup.citation")),
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
