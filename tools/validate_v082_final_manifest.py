#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

CJK_RE = re.compile(r"[\u3400-\u9fff]")


def plain(items: list[dict]) -> str:
    return "".join(str(x.get("text", "")) for x in items)


def validate(manifest: dict, schema: dict, audit: dict | None) -> dict:
    errors = [e.message for e in Draft202012Validator(schema).iter_errors(manifest)]
    paragraphs = [b for s in manifest["sections"] for b in s["blocks"] if b["type"] == "paragraph"]
    assets = manifest["assets"]
    refs = manifest["references"]
    source_chars = sum(len(plain(b["english"])) for b in paragraphs)
    zh_chars = sum(len(plain(b["chinese"])) for b in paragraphs)
    cjk_chars = sum(len(CJK_RE.findall(plain(b["chinese"]))) for b in paragraphs)
    cjk_ratio = cjk_chars / max(1, zh_chars)
    pages = manifest["paper"]["pages"]
    if len(paragraphs) < max(20, pages * 2):
        errors.append(f"too few paragraph blocks: {len(paragraphs)} for {pages} pages")
    if not assets:
        errors.append("no figure/table assets")
    if source_chars < pages * 1200:
        errors.append(f"source text coverage too low: {source_chars} characters for {pages} pages")
    if cjk_ratio < 0.18:
        errors.append(f"Chinese translation ratio too low: {cjk_ratio:.3f}")
    if any(not b.get("source_fragments") for b in paragraphs):
        errors.append("paragraph without source_fragments")
    if any(not a.get("image_src", "").startswith("data:image/") for a in assets if a["kind"] == "figure"):
        errors.append("figure asset without embedded source image")
    if len({a["id"] for a in assets}) != len(assets):
        errors.append("duplicate asset IDs")
    asset_refs = [b["asset_id"] for s in manifest["sections"] for b in s["blocks"] if b["type"] == "asset"]
    if len(asset_refs) != len(set(asset_refs)):
        errors.append("duplicate asset card placement")
    if set(asset_refs) != {a["id"] for a in assets}:
        errors.append("asset inventory and section placement differ")
    if audit and not audit.get("passed"):
        errors.append("PDF-native extraction audit failed")
    if audit and audit.get("paragraphs") != len(paragraphs):
        errors.append(f"audit/manifest paragraph mismatch: {audit.get('paragraphs')} != {len(paragraphs)}")
    if audit and audit.get("assets") != len(assets):
        errors.append(f"audit/manifest asset mismatch: {audit.get('assets')} != {len(assets)}")
    return {
        "paper_key": manifest["paper"]["key"],
        "pages": pages,
        "sections": len(manifest["sections"]),
        "paragraphs": len(paragraphs),
        "assets": len(assets),
        "references": len(refs),
        "source_chars": source_chars,
        "translated_chars": zh_chars,
        "cjk_ratio": round(cjk_ratio, 4),
        "errors": errors,
        "passed": not errors,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Strict content validation for final V0.8.2 manifests")
    p.add_argument("manifest", type=Path)
    p.add_argument("--schema", type=Path, required=True)
    p.add_argument("--audit", type=Path)
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    manifest = json.loads(args.manifest.read_text("utf-8"))
    schema = json.loads(args.schema.read_text("utf-8"))
    audit = json.loads(args.audit.read_text("utf-8")) if args.audit else None
    report = validate(manifest, schema, audit)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
