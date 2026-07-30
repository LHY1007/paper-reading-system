#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import io
import json
import re
from pathlib import Path
from statistics import median
from typing import Any

from bs4 import BeautifulSoup
from PIL import Image

import audit_v082_reader_experience as base


ORIGINAL_EXTRACT = base.extract_reader
ORIGINAL_SCORE = base.score_reader
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
TABLE_TITLE_RE = re.compile(r"^(?:Extended Data |Supplementary )?Table\b", re.I)


def image_dimensions(source: str) -> tuple[int, int] | None:
    if not source.startswith("data:image/") or "," not in source:
        return None
    header, payload = source.split(",", 1)
    try:
        raw = base64.b64decode(payload) if ";base64" in header else payload.encode("utf-8")
        with Image.open(io.BytesIO(raw)) as image:
            return int(image.width), int(image.height)
    except Exception:
        return None


def suspicious_reference(text: str) -> bool:
    value = base.norm(text)
    value = re.sub(r"^\s*\d+[.)]?\s*", "", value)
    if not value:
        return True
    if not YEAR_RE.search(value):
        return True
    if len(value) < 35:
        return True
    if re.match(
        r"^(?:Conversely|Together|We |Our |This |These |Here |When |Although |However |In line with|The second largest|Within |Based on)",
        value,
        re.I,
    ):
        return True
    return False


def extract_reader(path: Path) -> dict[str, Any]:
    report = ORIGINAL_EXTRACT(path)
    soup = BeautifulSoup(path.read_text("utf-8", errors="ignore"), "lxml")

    widths: list[int] = []
    heights: list[int] = []
    low_resolution_ids: list[str] = []
    for figure in soup.select(".figure-card"):
        image = figure.select_one("img")
        if image is None:
            continue
        dimensions = image_dimensions(str(image.get("src", "")))
        if dimensions is None:
            continue
        width, height = dimensions
        widths.append(width)
        heights.append(height)
        if width < 1600:
            low_resolution_ids.append(str(figure.get("id") or "unknown"))

    references = [base.norm(item.get_text(" ", strip=True)) for item in soup.select(".reference-item")]
    suspicious_references = [
        {"index": index + 1, "text": text[:500]}
        for index, text in enumerate(references)
        if suspicious_reference(text)
    ]
    table_like_figures = [
        item.get("id")
        for item in report.get("figures", {}).get("items", [])
        if TABLE_TITLE_RE.match(base.norm(item.get("title")))
    ]

    report["figures"]["image_widths"] = widths
    report["figures"]["median_image_width"] = int(median(widths)) if widths else None
    report["figures"]["median_image_height"] = int(median(heights)) if heights else None
    report["figures"]["low_resolution_count"] = len(low_resolution_ids)
    report["figures"]["low_resolution_ids"] = low_resolution_ids
    report["tables"]["table_like_figure_ids"] = table_like_figures
    report["references"]["suspicious_count"] = len(suspicious_references)
    report["references"]["suspicious_items"] = suspicious_references[:30]
    return report


def score_reader(reader: dict[str, Any], baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    result = ORIGINAL_SCORE(reader, baseline)
    modules = result["modules"]

    table_like_figures = reader.get("tables", {}).get("table_like_figure_ids", [])
    structured_table_count = int(reader.get("tables", {}).get("count", 0) or 0)
    unresolved_table_images = max(0, len(table_like_figures) - structured_table_count)
    modules["tables"] = max(0, round(5 * (1 - unresolved_table_images / max(1, len(table_like_figures))), 1))

    reference_count = int(reader.get("references", {}).get("count", 0) or 0)
    suspicious_count = int(reader.get("references", {}).get("suspicious_count", 0) or 0)
    if reference_count == 0:
        modules["references"] = 0
    else:
        modules["references"] = max(0, round(5 * (1 - suspicious_count / reference_count), 1))

    figure_count = max(1, int(reader.get("figures", {}).get("count", 0) or 0))
    low_resolution_count = int(reader.get("figures", {}).get("low_resolution_count", 0) or 0)
    resolution_penalty = min(2.0, round(2.0 * low_resolution_count / figure_count, 1))
    modules["figures"] = max(0, round(float(modules["figures"]) - resolution_penalty, 1))

    result["total"] = round(sum(float(value) for value in modules.values()), 1)
    result["scoring_note"] = (
        "Table and reference quantities are paper-specific. A table loses points only when its table-like figure has no corresponding structured table card; "
        "references lose points for bibliographically implausible body-text contamination. Figure score also includes source-image resolution."
    )
    return result


base.extract_reader = extract_reader
base.score_reader = score_reader


def main() -> None:
    parser = argparse.ArgumentParser(description="Reader-facing V0.8.2 audit with paper-specific table/reference and image-resolution checks")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--md", type=Path)
    parser.add_argument("--minimum-score", type=float)
    args = parser.parse_args()

    reports = [extract_reader(path) for path in args.files]
    baseline = reports[0]
    for report in reports:
        report["reader_score"] = score_reader(report, baseline if report is not baseline else None)

    payload = {
        "version": "v082-reader-experience-audit-2",
        "baseline": baseline["file"],
        "reports": reports,
    }
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        markdown = base.render_markdown(reports)
        markdown += "\n## V2 additional diagnostics\n\n"
        for report in reports:
            markdown += (
                f"- {report['file']}: median figure width={report['figures'].get('median_image_width')}, "
                f"low-resolution figures={report['figures'].get('low_resolution_count')}, "
                f"table-like figures={len(report['tables'].get('table_like_figure_ids', []))}, "
                f"suspicious references={report['references'].get('suspicious_count')}.\n"
            )
        args.md.write_text(markdown, "utf-8")

    print(json.dumps([{report["file"]: report["reader_score"]} for report in reports], ensure_ascii=False, indent=2))
    if args.minimum_score is not None:
        failures = [
            report["file"]
            for report in reports[1:]
            if report["reader_score"]["total"] < args.minimum_score
        ]
        if failures:
            raise SystemExit(f"reader-experience score below {args.minimum_score}: {', '.join(failures)}")


if __name__ == "__main__":
    main()
