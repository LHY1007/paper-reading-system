#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup

CANONICAL_SHA256 = "84c37e235f40e782c79de6625ddd9369cba64095f28bff75ae702fb5893f6ff1"
DYNAMIC_SCRIPT_IDS = {
    "v080ReviewManifest",
    "canvas-reader-v060-script",
    "canvas-reader-v061-script",
    "canvas-v082-script",
}
CONTENT_SELECTORS = [
    "title",
    "#topbar .brand",
    ".hero",
    "#quick-pane",
    "#bilingual-pane",
]
REQUIRED_FIXED_SELECTORS = [
    "#topbar",
    "#tocBtn",
    "#searchInput",
    "#searchBtn",
    "#immersiveBtn",
    "#settingsBtn",
    "#annotationBtn",
    "#pdfBtn",
    "#printBtn",
    "#sidebar",
    "#toc",
    "#leftResizeHandle.resizer.left-resizer",
    "#rightResizeHandle.resizer.right-resizer",
    "#viewer.viewer",
    "#settings.settings",
    ".settings-backdrop",
    ".annotation-toolbar",
    ".annotation-drawer",
    "#termTooltip.term-tooltip",
    ".reference-pop",
    ".modal .zoom-stage",
    ".image-magnifier",
    "#quick-pane.mode-pane",
    "#bilingual-pane.mode-pane",
]
FORBIDDEN_BATCH_TOKENS = [
    'meta name="reader-version" content="0.8.2"',
    "class=\"para-card\"",
    "V0.8.2 SEQUENTIAL BUILD",
    "核心双语段落 12",
]


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def style_hashes(soup: BeautifulSoup) -> list[str]:
    return [sha_text(tag.get_text()) for tag in soup.find_all("style")]


def script_inventory(soup: BeautifulSoup) -> list[dict]:
    rows = []
    for index, tag in enumerate(soup.find_all("script")):
        dynamic = tag.get("id") in DYNAMIC_SCRIPT_IDS or (tag.get("type") == "application/json" and not tag.get("id"))
        rows.append({
            "index": index,
            "id": tag.get("id"),
            "type": tag.get("type"),
            "src": tag.get("src"),
            "dynamic": dynamic,
            "sha256": None if dynamic else sha_text(tag.get_text()),
        })
    return rows


def direct_signature(node) -> list[dict]:
    if node is None:
        return []
    out = []
    for child in node.find_all(recursive=False):
        if not getattr(child, "name", None):
            continue
        out.append({
            "tag": child.name,
            "id": child.get("id"),
            "classes": list(child.get("class") or []),
        })
    return out


def neutralize(path: Path) -> tuple[str, dict]:
    raw = path.read_text("utf-8")
    soup = BeautifulSoup(raw, "html.parser")
    errors: list[str] = []

    for selector in CONTENT_SELECTORS:
        nodes = soup.select(selector)
        if len(nodes) != 1:
            errors.append(f"content slot {selector!r} expected once, found {len(nodes)}")
            continue
        node = nodes[0]
        if node.name == "title":
            node.string = "__PAPER_TITLE__"
        else:
            node.clear()
            node.append(f"__CONTENT_SLOT__{selector}")

    if soup.body:
        soup.body["data-paper-key"] = "__PAPER_KEY__"
        soup.body["data-mode"] = "bilingual"

    for tag in soup.find_all("script"):
        if tag.get("id") in DYNAMIC_SCRIPT_IDS or (tag.get("type") == "application/json" and not tag.get("id")):
            tag.string = "__PAPER_DATA__"

    return str(soup), {
        "errors": errors,
        "style_hashes": style_hashes(soup),
        "script_inventory": script_inventory(soup),
        "topbar_children": direct_signature(soup.select_one("#topbar")),
        "layout_children": direct_signature(soup.select_one(".layout")),
        "body_children": direct_signature(soup.body),
    }


def analyze(canonical: Path, candidate: Path) -> dict:
    canonical_raw = canonical.read_text("utf-8")
    candidate_raw = candidate.read_text("utf-8")
    canonical_sha = hashlib.sha256(canonical.read_bytes()).hexdigest()
    can_norm, can_meta = neutralize(canonical)
    out_norm, out_meta = neutralize(candidate)
    out_soup = BeautifulSoup(candidate_raw, "html.parser")

    errors = []
    if canonical_sha != CANONICAL_SHA256:
        errors.append(f"canonical SHA mismatch: {canonical_sha}")
    errors.extend("canonical: " + e for e in can_meta["errors"])
    errors.extend("candidate: " + e for e in out_meta["errors"])

    if can_meta["style_hashes"] != out_meta["style_hashes"]:
        errors.append("style blocks differ from canonical CANVAS")
    if can_meta["script_inventory"] != out_meta["script_inventory"]:
        errors.append("static script inventory or hashes differ from canonical CANVAS")
    if can_meta["topbar_children"] != out_meta["topbar_children"]:
        errors.append("topbar child order differs")
    if can_meta["layout_children"] != out_meta["layout_children"]:
        errors.append("layout child order differs")
    if can_meta["body_children"] != out_meta["body_children"]:
        errors.append("body fixed-node order differs")

    for selector in REQUIRED_FIXED_SELECTORS:
        count = len(out_soup.select(selector))
        if count != 1:
            errors.append(f"required fixed selector {selector!r}: expected 1, found {count}")

    for token in FORBIDDEN_BATCH_TOKENS:
        if token in candidate_raw:
            errors.append("forbidden simplified-batch token: " + token)

    if sha_text(can_norm) != sha_text(out_norm):
        errors.append("neutralized DOM shell differs from canonical CANVAS")

    return {
        "canonical": canonical.name,
        "candidate": candidate.name,
        "canonical_sha256": canonical_sha,
        "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "canonical_shell_sha256": sha_text(can_norm),
        "candidate_shell_sha256": sha_text(out_norm),
        "canonical_style_hashes": can_meta["style_hashes"],
        "candidate_style_hashes": out_meta["style_hashes"],
        "topbar_children": out_meta["topbar_children"],
        "layout_children": out_meta["layout_children"],
        "errors": errors,
        "passed": not errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate exact V0.8.2 CANVAS shell parity while allowing paper-content slots to differ")
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = analyze(args.canonical, args.candidate)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", "utf-8")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
