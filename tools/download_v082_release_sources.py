#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from bs4 import BeautifulSoup
import requests

import download_v082_sources as source_tools


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_report(
    path: Path,
    registry_version: str,
    expected: int,
    results: list[dict],
    failures: list[dict],
) -> None:
    payload = {
        "registry_version": registry_version,
        "source_contract": {
            "canonical_order_0": "locked and independently validated CANVAS HTML baseline",
            "orders_1_to_11": "downloaded original article PDFs with page-count and SHA-256 audit",
        },
        "expected_papers": expected,
        "completed_papers": len(results),
        "papers": results,
        "failures": failures,
        "passed": len(results) == expected and not failures,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")


def locate_canonical(explicit: Path | None) -> Path:
    if explicit is not None:
        if not explicit.exists():
            raise FileNotFoundError(explicit)
        return explicit
    candidates = sorted(Path(".").glob("00_V0.8.2_CANVAS*.html"))
    if len(candidates) != 1:
        raise RuntimeError(f"expected exactly one canonical CANVAS HTML, found {len(candidates)}")
    return candidates[0]


def audit_canonical(path: Path, paper: dict) -> dict:
    raw = path.read_bytes()
    soup = BeautifulSoup(raw, "html.parser")
    counts = {
        "bilingual_units": len(soup.select(".bilingual-unit")),
        "figure_cards": len(soup.select(".figure-card")),
        "table_cards": len(soup.select(".table-card")),
        "reference_items": len(soup.select(".reference-item")),
    }
    errors = []
    if counts["bilingual_units"] < 100:
        errors.append("canonical CANVAS has fewer than 100 bilingual units")
    if counts["figure_cards"] < 10:
        errors.append("canonical CANVAS has fewer than 10 figure cards")
    if counts["reference_items"] < 100:
        errors.append("canonical CANVAS has fewer than 100 references")
    if errors:
        raise RuntimeError("; ".join(errors))
    return {
        "order": paper["order"],
        "key": paper["key"],
        "doi": paper["doi"],
        "source_mode": "locked_canonical_html",
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "pages": paper["expected_pages"],
        "component_counts": counts,
        "audit_note": (
            "Order 0 is not regenerated from a downloaded PDF. It is the normalized product and content baseline; "
            "PDF-native extraction is exercised independently by orders 1-11."
        ),
    }


def discover_candidates(session: requests.Session, paper: dict) -> tuple[list[str], dict]:
    candidates = list(paper.get("download_candidates", []))
    candidates.append(f"https://doi.org/{paper['doi']}")
    discovery: dict = {}
    discovery_calls = [
        ("pmc", lambda: source_tools.discover_pmc_urls(session, paper["doi"])),
        ("europepmc", lambda: source_tools.discover_europepmc_metadata_urls(session, paper["doi"])),
        ("unpaywall", lambda: source_tools.discover_unpaywall_urls(session, paper["doi"])),
        ("openalex", lambda: source_tools.discover_openalex_urls(session, paper["doi"])),
        ("semantic_scholar", lambda: source_tools.discover_semantic_scholar_urls(session, paper["doi"])),
        ("crossref", lambda: source_tools.discover_crossref_urls(session, paper["doi"])),
        ("doi", lambda: source_tools.discover_doi_urls(session, paper["doi"])),
    ]
    for name, discover in discovery_calls:
        try:
            urls, info = discover()
            candidates.extend(urls)
            discovery[name] = info
        except Exception as exc:  # discovery sources are redundant; all failures remain audited
            discovery[name] = {"error": f"{type(exc).__name__}: {exc}"}
    candidates.extend(source_tools.discover_elsevier_urls(paper["doi"]))
    return source_tools.dedupe(candidates), discovery


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit the canonical CANVAS input and download all non-CANVAS source PDFs")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--canonical-html", type=Path)
    parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args()

    registry = json.loads(args.registry.read_text("utf-8"))
    papers = sorted(registry["papers"], key=lambda item: item["order"])
    if not papers or papers[0]["order"] != 0:
        raise RuntimeError("registry must start with canonical order 0")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    failures: list[dict] = []

    try:
        canonical = locate_canonical(args.canonical_html)
        results.append(audit_canonical(canonical, papers[0]))
    except Exception as exc:
        failures.append({
            "order": 0,
            "key": papers[0].get("key", "canvas"),
            "error": f"{type(exc).__name__}: {exc}",
        })
        write_report(args.report, registry["version"], len(papers), results, failures)
        raise

    session = requests.Session()
    session.headers.update({"User-Agent": source_tools.UA})
    for paper in papers[1:]:
        key = paper["key"]
        target = args.output_dir / f"{paper['order']:02d}_{key}.pdf"
        print(f"===== SOURCE {paper['order']:02d} {key} =====", flush=True)
        if args.reuse and target.exists():
            data = target.read_bytes()
            validation = source_tools.validate_pdf(data, paper["expected_pages"])
            results.append({
                "order": paper["order"],
                "key": key,
                "doi": paper["doi"],
                "source_mode": "reused_pdf",
                "path": str(target),
                "sha256": hashlib.sha256(data).hexdigest(),
                **validation,
            })
            write_report(args.report, registry["version"], len(papers), results, failures)
            continue

        candidates, discovery = discover_candidates(session, paper)
        attempts: list[dict] = []
        try:
            data, final_url, attempts = source_tools.fetch_pdf(session, candidates)
            validation = source_tools.validate_pdf(data, paper["expected_pages"])
        except Exception as exc:
            if isinstance(exc, source_tools.DownloadError):
                attempts = exc.attempts
            failure = {
                "order": paper["order"],
                "key": key,
                "doi": paper["doi"],
                "error": f"{type(exc).__name__}: {exc}",
                "discovery": discovery,
                "candidates": candidates,
                "attempts": attempts,
            }
            failures.append(failure)
            write_report(args.report, registry["version"], len(papers), results, failures)
            print(json.dumps(failure, ensure_ascii=False, indent=2), flush=True)
            raise

        target.write_bytes(data)
        results.append({
            "order": paper["order"],
            "key": key,
            "doi": paper["doi"],
            "source_mode": "downloaded_pdf",
            "path": str(target),
            "final_url": final_url,
            "sha256": hashlib.sha256(data).hexdigest(),
            "discovery": discovery,
            "attempts": attempts,
            **validation,
        })
        write_report(args.report, registry["version"], len(papers), results, failures)
        print(json.dumps({"key": key, "pages": validation["pages"], "final_url": final_url}, ensure_ascii=False), flush=True)
        time.sleep(1)

    write_report(args.report, registry["version"], len(papers), results, failures)
    print(json.dumps({"papers": len(results), "passed": len(results) == len(papers)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
