#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import statistics
from pathlib import Path

import fitz


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def join_lines(lines: list[str]) -> str:
    out = ""
    for line in lines:
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if out.endswith("-") and line[0].islower():
            out = out[:-1] + line
        else:
            out += (" " if out else "") + line
    return out.strip()


def audit(path: Path) -> dict:
    doc = fitz.open(path)
    pages: list[list[dict]] = []
    repeated_candidates: collections.Counter[str] = collections.Counter()
    sizes: list[float] = []
    for page in doc:
        page_items = []
        page_height = page.rect.height
        for block in page.get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0:
                continue
            lines, block_sizes = [], []
            for line in block.get("lines", []):
                text = "".join(span.get("text", "") for span in line.get("spans", []))
                if text.strip():
                    lines.append(text)
                for span in line.get("spans", []):
                    if span.get("text", "").strip():
                        size = float(span.get("size", 0))
                        sizes.append(size)
                        block_sizes.append(size)
            text = join_lines(lines)
            if not text:
                continue
            x0, y0, x1, y1 = block["bbox"]
            normalized = re.sub(r"\d+", "#", text)
            if y0 < page_height * 0.08 or y1 > page_height * 0.92:
                repeated_candidates[normalized] += 1
            page_items.append({
                "text": text,
                "bbox": [x0, y0, x1, y1],
                "size": statistics.median(block_sizes) if block_sizes else 0,
            })
        pages.append(page_items)

    body_size = statistics.median(size for size in sizes if 5 < size < 20)
    repeated = {
        text for text, count in repeated_candidates.items()
        if count >= max(3, int(len(doc) * 0.12))
    }
    counts: collections.Counter[str] = collections.Counter()
    for page_number, blocks in enumerate(pages, 1):
        height = doc[page_number - 1].rect.height
        for block in blocks:
            text = block["text"]
            normalized = re.sub(r"\d+", "#", text)
            y0, y1 = block["bbox"][1], block["bbox"][3]
            if (y0 < height * 0.08 or y1 > height * 0.92) and normalized in repeated:
                kind = "header_footer"
            elif re.match(r"^(?:Figure|Fig\.|Extended Data Fig\.|Table|Figure S|Table S)\s*\d+", text, re.I):
                kind = "caption"
            elif len(text) < 180 and (block["size"] >= body_size + 0.8 or (text.isupper() and len(text) > 3)):
                kind = "heading"
            elif len(text) >= 40:
                kind = "body"
            else:
                kind = "other"
            counts[kind] += 1

    return {
        "file": path.name,
        "sha256": sha256(path),
        "pages": len(doc),
        "body_font_size": body_size,
        "body_text_blocks": counts["body"],
        "figure_table_captions": counts["caption"],
        "heading_blocks": counts["heading"],
        "header_footer_blocks_removed": counts["header_footer"],
        "other_blocks": counts["other"],
        "minimum_expected_bilingual_units": max(18, int(len(doc) * 1.1)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit PDF structure before generating a reader")
    parser.add_argument("pdf", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {
        "method": "PDF-native sorted text-block audit; repeated headers/footers removed before coverage expectations are defined",
        "papers": [audit(path) for path in args.pdf],
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", "utf-8")


if __name__ == "__main__":
    main()
