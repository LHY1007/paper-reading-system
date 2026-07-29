#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

import render_v082_canvas_component_locked_v2 as locked_renderer


PAPER_META_KEYS = {
    "description",
    "citation_title",
    "citation_author",
    "citation_doi",
    "citation_journal_title",
    "citation_publication_date",
    "og:title",
    "og:description",
    "twitter:title",
    "twitter:description",
}


def paper_description(paper: dict[str, Any]) -> str:
    return str(
        paper.get("description")
        or paper.get("abstract")
        or f"Bilingual structured reader for {paper['title_en']}."
    )


def fill_document_metadata(soup: BeautifulSoup, paper: dict[str, Any]) -> None:
    values = {
        "description": paper_description(paper),
        "citation_title": paper["title_en"],
        "citation_author": ", ".join(paper["authors"]),
        "citation_doi": paper["doi"],
        "citation_journal_title": paper["journal"],
        "citation_publication_date": str(paper["year"]),
        "og:title": paper["title_en"],
        "og:description": paper_description(paper),
        "twitter:title": paper["title_en"],
        "twitter:description": paper_description(paper),
    }
    for meta in soup.find_all("meta"):
        key = str(meta.get("name") or meta.get("property") or "").lower()
        if key in PAPER_META_KEYS:
            meta["content"] = values[key]
    article_url = paper.get("article_url") or (f"https://doi.org/{paper['doi']}" if paper.get("doi") else "")
    for link in soup.find_all("link"):
        rel = {str(value).lower() for value in (link.get("rel") or [])}
        if "canonical" in rel and article_url:
            link["href"] = article_url


def render(shell: Path, manifest_path: Path, output: Path, schema: Path | None) -> dict[str, Any]:
    shell_raw = shell.read_text("utf-8")
    shell_soup = BeautifulSoup(shell_raw, "html.parser")
    if shell_soup.select_one('html[data-v082-template="frozen-shell"]') is None:
        raise SystemExit("renderer input is not a frozen V0.8.2 CANVAS shell")
    shell_sha = hashlib.sha256(shell.read_bytes()).hexdigest()

    report = locked_renderer.core.render(shell, manifest_path, output, schema)
    manifest = json.loads(manifest_path.read_text("utf-8"))
    soup = BeautifulSoup(output.read_text("utf-8"), "html.parser")
    fill_document_metadata(soup, manifest["paper"])
    soup.html["data-v082-template"] = "frozen-shell-rendered"
    soup.html["data-v082-shell-sha256"] = shell_sha
    output.write_text(str(soup), "utf-8")

    raw = output.read_text("utf-8")
    unresolved = sorted({token.split("__", 1)[0] for token in raw.split("__V082_")[1:]})
    if "__V082_" in raw:
        sample = [fragment[:80] for fragment in raw.split("__V082_")[1:6]]
        raise SystemExit(f"unresolved frozen-shell placeholders remain: {sample}")

    report.update(
        {
            "renderer": "v082-frozen-shell-1",
            "shell": str(shell),
            "shell_sha256": shell_sha,
            "manifest": str(manifest_path),
            "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "unresolved_placeholders": unresolved,
        }
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Render paper data through the immutable V0.8.2 CANVAS shell")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--shell", type=Path, required=True)
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = render(args.shell, args.manifest, args.output, args.schema)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", "utf-8")


if __name__ == "__main__":
    main()
