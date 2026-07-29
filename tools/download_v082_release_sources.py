#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import deque
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup
import requests

import download_v082_sources as source_tools

ORIGINAL_PUBLISHER_VARIANTS = source_tools.publisher_variants
PMC_PDF_RE = re.compile(r"/articles/(PMC\d+)/pdf/([^/?#]+\.pdf)", re.I)
PMC_ARTICLE_RE = re.compile(r"/articles/(PMC\d+)/?$", re.I)
CELL_STEM_RE = re.compile(r"(S\d{4}-\d{4}\(\d{2}\)\d{5}-\d)", re.I)
COMPACT_PII_RE = re.compile(r"(S\d{16})", re.I)
EMBEDDED_URL_RE = re.compile(r"https?(?::|%3A)(?:\\?/|%2F){2}[^\"'<>\\s]+", re.I)


def cell_stem_to_compact(stem: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", stem).upper()


def compact_to_cell_stem(compact: str) -> str | None:
    compact = compact.upper()
    if not re.fullmatch(r"S\d{16}", compact):
        return None
    return f"{compact[:5]}-{compact[5:9]}({compact[9:11]}){compact[11:16]}-{compact[16]}"


def release_publisher_variants(url: str) -> list[str]:
    variants = list(ORIGINAL_PUBLISHER_VARIANTS(url))
    parsed = urlparse(url)
    match = PMC_PDF_RE.search(parsed.path)
    if match:
        pmcid, filename = match.groups()
        numeric = re.sub(r"\D", "", pmcid)
        variants.extend([
            f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/bin/{filename}",
            f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/{filename}?download=1",
            f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/{filename}?report=reader",
            f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/{filename}",
            f"https://pmc.ncbi.nlm.nih.gov/articles/instance/{numeric}/bin/{filename}",
        ])
    article_match = PMC_ARTICLE_RE.search(parsed.path)
    if article_match:
        pmcid = article_match.group(1)
        variants.extend([
            f"https://europepmc.org/articles/{pmcid}?pdf=render",
            f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf",
        ])

    decoded_url = requests.utils.unquote(url)
    stem_match = CELL_STEM_RE.search(decoded_url)
    compact_match = COMPACT_PII_RE.search(decoded_url)
    stem = stem_match.group(1).upper() if stem_match else None
    compact = compact_match.group(1).upper() if compact_match else None
    if stem and not compact:
        compact = cell_stem_to_compact(stem)
    if compact and not stem:
        stem = compact_to_cell_stem(compact)
    if stem and compact:
        escaped_stem = quote(stem, safe="")
        variants.extend([
            f"https://www.cell.com/action/showPdf?pii={escaped_stem}",
            f"https://www.cell.com/cell/pdfExtended/{stem}",
            f"https://www.cell.com/cell/fulltext/{stem}",
            f"https://www.cell.com/cell/fulltext/{stem}?download=true",
            f"https://www.sciencedirect.com/science/article/pii/{compact}/pdfft?download=true",
            f"https://www.sciencedirect.com/science/article/pii/{compact}/pdfft?isDTMRedir=true&download=true",
            f"https://api.elsevier.com/content/article/pii/{compact}?view=FULL&httpAccept=application/pdf",
            f"https://api.elsevier.com/content/article/pii/{compact}?httpAccept=application/pdf",
        ])
    return source_tools.dedupe(variants)


source_tools.publisher_variants = release_publisher_variants


def decode_embedded_url(value: str) -> str:
    value = value.replace("\\/", "/")
    value = requests.utils.unquote(value)
    return value.rstrip("\\,;)")


def extract_embedded_pdf_links(base_url: str, body: str) -> list[str]:
    links = list(source_tools.extract_pdf_links(base_url, body))
    soup = BeautifulSoup(body, "html.parser")
    for node in soup.find_all(True):
        for attribute in ("data-pdf-url", "data-download-url", "data-url", "href", "src"):
            raw = node.get(attribute)
            if raw and ("pdf" in raw.lower() or "pdfft" in raw.lower() or "showpdf" in raw.lower()):
                links.append(urljoin(base_url, decode_embedded_url(raw)))
    for raw in EMBEDDED_URL_RE.findall(body):
        decoded = decode_embedded_url(raw)
        if any(token in decoded.lower() for token in (".pdf", "/pdf", "pdfft", "showpdf", "sciencedirectassets")):
            links.append(decoded)
    return source_tools.dedupe(links)


def release_fetch_pdf(
    session: requests.Session,
    urls: list[str],
    *,
    max_requests: int = 160,
) -> tuple[bytes, str, list[dict]]:
    attempts: list[dict] = []
    queue: deque[str] = deque()
    queued: set[str] = set()
    for url in urls:
        for variant in release_publisher_variants(url):
            if variant not in queued:
                queued.add(variant)
                queue.append(variant)

    while queue and len(attempts) < max_requests:
        url = queue.popleft()
        lower = url.lower()
        pdf_only = any(token in lower for token in (
            ".pdf", "pdfft", "showpdf", "pdfextended", "httpaccept=application/pdf", "fulltextpdf"
        ))
        try:
            response = session.get(
                url,
                timeout=180,
                allow_redirects=True,
                headers=source_tools.request_headers(url, pdf_only=pdf_only),
            )
            content_type = response.headers.get("content-type", "")
            attempt = {
                "url": url,
                "final_url": response.url,
                "status": response.status_code,
                "content_type": content_type,
                "bytes": len(response.content),
            }
            attempts.append(attempt)
            if source_tools.is_pdf(response.content, content_type) and len(response.content) > 10_000:
                return response.content, response.url, attempts

            looks_html = "html" in content_type.lower() or response.content.lstrip().startswith(b"<")
            if looks_html and len(response.content) <= 8_000_000:
                body = response.text
                nested = extract_embedded_pdf_links(response.url, body)
                attempt["nested_pdf_links"] = len(nested)
                for nested_url in nested:
                    for variant in release_publisher_variants(nested_url):
                        if variant not in queued:
                            queued.add(variant)
                            queue.append(variant)
        except Exception as exc:
            attempts.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
    raise source_tools.DownloadError(
        f"all PDF download candidates failed after {len(attempts)} attempts",
        attempts,
    )


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
        except Exception as exc:
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
            data, final_url, attempts = release_fetch_pdf(session, candidates)
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
