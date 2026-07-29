#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import fitz
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149 Safari/537.36"
PDF_ACCEPT = "application/pdf,text/html;q=0.9,application/xhtml+xml;q=0.8,*/*;q=0.5"


class DownloadError(RuntimeError):
    def __init__(self, message: str, attempts: list[dict]) -> None:
        super().__init__(message)
        self.attempts = attempts


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_pdf(data: bytes, content_type: str = "") -> bool:
    return data.startswith(b"%PDF-") or "application/pdf" in content_type.lower()


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        value = value.strip()
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def normalize_download_url(url: str) -> str:
    if url.startswith("ftp://ftp.ncbi.nlm.nih.gov/"):
        return "https://ftp.ncbi.nlm.nih.gov/" + url.removeprefix("ftp://ftp.ncbi.nlm.nih.gov/")
    return url


def request_headers(url: str, *, pdf_only: bool = False) -> dict[str, str]:
    host = urlparse(url).netloc.lower()
    headers = {
        "Accept": "application/pdf" if pdf_only else PDF_ACCEPT,
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }
    if "cell.com" in host or "sciencedirect.com" in host or "elsevier.com" in host:
        headers["Referer"] = "https://www.sciencedirect.com/"
    elif "science.org" in host:
        headers["Referer"] = "https://www.science.org/"
    elif "nature.com" in host:
        headers["Referer"] = "https://www.nature.com/"
    elif "pmc.ncbi.nlm.nih.gov" in host or "ncbi.nlm.nih.gov" in host:
        headers["Referer"] = "https://pmc.ncbi.nlm.nih.gov/"
    return headers


def publisher_variants(url: str) -> list[str]:
    url = normalize_download_url(url)
    variants = [url]
    low = url.lower()
    if "cell.com/" in low and "/pdf/" in low:
        variants.append(url + ("&" if "?" in url else "?") + "download=true")
        match = re.search(r"/(S\d{16})\.pdf", url, flags=re.I)
        if match:
            pii = match.group(1)
            variants.extend(
                [
                    f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft?isDTMRedir=true&download=true",
                    f"https://api.elsevier.com/content/article/pii/{pii}?httpAccept=application/pdf",
                ]
            )
    if "science.org/doi/pdf/" in low:
        variants.extend(
            [
                url + ("&" if "?" in url else "?") + "download=true",
                url.replace("/doi/pdf/", "/doi/epdf/"),
            ]
        )
    if "science.org/doi/" in low and "/pdf/" not in low and "/epdf/" not in low:
        doi = url.split("/doi/", 1)[1].split("?", 1)[0]
        variants.extend(
            [
                f"https://www.science.org/doi/pdf/{doi}?download=true",
                f"https://www.science.org/doi/epdf/{doi}",
            ]
        )
    return dedupe(variants)


def extract_pdf_links(base_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    selectors = [
        'meta[name="citation_pdf_url"]',
        'meta[name="wkhealth_pdf_url"]',
        'meta[property="og:pdf"]',
        'meta[name="pdf_url"]',
        'link[type="application/pdf"]',
        'a[href*=".pdf"]',
        'a[href*="/pdf/"]',
        'a[href*="/epdf/"]',
        'iframe[src*=".pdf"]',
        'iframe[src*="/pdf/"]',
        'embed[src*=".pdf"]',
    ]
    for selector in selectors:
        for node in soup.select(selector):
            href = node.get("content") or node.get("href") or node.get("src")
            if href:
                urls.append(normalize_download_url(urljoin(base_url, href)))
    for link in soup.find_all("a", href=True):
        href = normalize_download_url(urljoin(base_url, link["href"]))
        label = " ".join(link.get_text(" ", strip=True).split()).lower()
        if "download pdf" in label or label == "pdf" or "full text pdf" in label:
            urls.append(href)
    for match in re.findall(
        r'https?://[^"\'<> ]+(?:/pdf/[^"\'<> ]+|/epdf/[^"\'<> ]+|\.pdf(?:\?[^"\'<> ]*)?)',
        html,
    ):
        urls.append(normalize_download_url(match.replace("\\/", "/")))
    return dedupe(urls)


def discover_doi_urls(session: requests.Session, doi: str) -> tuple[list[str], dict]:
    landing = f"https://doi.org/{doi}"
    response = session.get(landing, timeout=90, allow_redirects=True, headers=request_headers(landing))
    response.raise_for_status()
    info = {
        "doi_landing": landing,
        "doi_final_url": response.url,
        "doi_status": response.status_code,
        "doi_content_type": response.headers.get("content-type", ""),
    }
    if is_pdf(response.content, info["doi_content_type"]):
        return [response.url], info
    return extract_pdf_links(response.url, response.text), info


def discover_pmc_urls(session: requests.Session, doi: str) -> tuple[list[str], dict]:
    id_endpoint = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
    response = session.get(
        id_endpoint,
        params={"ids": doi, "format": "json", "tool": "paper-reading-system", "email": "noreply@example.com"},
        timeout=60,
        headers=request_headers(id_endpoint),
    )
    response.raise_for_status()
    records = response.json().get("records", [])
    pmcid = next((record.get("pmcid") for record in records if record.get("pmcid")), None)
    if not pmcid:
        return [], {"pmc_found": False}

    urls: list[str] = []
    info: dict = {"pmc_found": True, "pmcid": pmcid}
    oa_endpoint = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"
    try:
        oa_response = session.get(
            oa_endpoint,
            params={"id": pmcid},
            timeout=60,
            headers=request_headers(oa_endpoint),
        )
        oa_response.raise_for_status()
        root = ET.fromstring(oa_response.content)
        oa_links = []
        for link in root.findall(".//link"):
            href = link.attrib.get("href")
            fmt = (link.attrib.get("format") or "").lower()
            if href and fmt == "pdf":
                normalized = normalize_download_url(href)
                oa_links.append(normalized)
                urls.append(normalized)
        info["oa_pdf_links"] = oa_links
        info["oa_response_bytes"] = len(oa_response.content)
    except Exception as exc:
        info["oa_error"] = f"{type(exc).__name__}: {exc}"

    article = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
    europe_candidates = [
        f"https://europepmc.org/articles/{pmcid}?pdf=render",
        f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf",
        f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextPDF",
    ]
    urls.extend(europe_candidates)
    urls.extend([article, f"{article}pdf/"])
    info["europe_pmc_candidates"] = europe_candidates
    return dedupe(urls), info


def discover_crossref_urls(session: requests.Session, doi: str) -> tuple[list[str], dict]:
    endpoint = f"https://api.crossref.org/works/{quote(doi, safe='')}"
    response = session.get(endpoint, timeout=60, headers=request_headers(endpoint))
    response.raise_for_status()
    message = response.json().get("message", {})
    urls: list[str] = []
    for link in message.get("link", []) or []:
        url = link.get("URL")
        content_type = (link.get("content-type") or "").lower()
        if url and ("pdf" in content_type or ".pdf" in url.lower() or "/pdf/" in url.lower()):
            urls.append(normalize_download_url(url))
    return dedupe(urls), {"crossref_links": len(urls)}


def discover_elsevier_urls(doi: str) -> list[str]:
    if not doi.startswith("10.1016/"):
        return []
    return [
        f"https://api.elsevier.com/content/article/doi/{doi}?httpAccept=application/pdf",
        f"https://api.elsevier.com/content/article/doi/{doi}",
    ]


def fetch_pdf(session: requests.Session, urls: list[str], *, max_requests: int = 100) -> tuple[bytes, str, list[dict]]:
    attempts: list[dict] = []
    queue: deque[str] = deque()
    queued: set[str] = set()
    for url in urls:
        for variant in publisher_variants(url):
            if variant not in queued:
                queued.add(variant)
                queue.append(variant)

    while queue and len(attempts) < max_requests:
        url = queue.popleft()
        try:
            response = session.get(
                url,
                timeout=180,
                allow_redirects=True,
                headers=request_headers(url),
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
            if response.ok and is_pdf(response.content, content_type) and len(response.content) > 10_000:
                return response.content, response.url, attempts
            if response.ok and ("html" in content_type.lower() or response.text.lstrip().startswith("<")):
                nested = extract_pdf_links(response.url, response.text)
                attempt["nested_pdf_links"] = len(nested)
                for nested_url in nested:
                    for variant in publisher_variants(nested_url):
                        if variant not in queued:
                            queued.add(variant)
                            queue.append(variant)
        except Exception as exc:
            attempts.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
    raise DownloadError(f"all PDF download candidates failed after {len(attempts)} attempts", attempts)


def validate_pdf(data: bytes, expected_pages: int) -> dict:
    doc = fitz.open(stream=data, filetype="pdf")
    pages = len(doc)
    first_text = " ".join(doc[0].get_text("text").split()) if pages else ""
    if pages < max(5, expected_pages - 3):
        raise RuntimeError(f"downloaded PDF has {pages} pages, expected approximately {expected_pages}")
    return {"pages": pages, "first_page_text": first_text[:500]}


def write_report(path: Path, registry_version: str, results: list[dict], failures: list[dict], expected: int) -> None:
    report = {
        "registry_version": registry_version,
        "expected_papers": expected,
        "completed_papers": len(results),
        "papers": results,
        "failures": failures,
        "passed": len(results) == expected and not failures,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and validate the audited PDFs used by the V0.8.2 final reader build")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args()

    registry = json.loads(args.registry.read_text("utf-8"))
    papers = sorted(registry["papers"], key=lambda item: item["order"])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    results: list[dict] = []
    failures: list[dict] = []

    for paper in papers:
        key = paper["key"]
        target = args.output_dir / f"{paper['order']:02d}_{key}.pdf"
        print(f"===== SOURCE {paper['order']:02d} {key} =====", flush=True)
        if args.reuse and target.exists():
            data = target.read_bytes()
            validation = validate_pdf(data, paper["expected_pages"])
            results.append(
                {"key": key, "path": str(target), "source": "reused", "sha256": sha256_bytes(data), **validation}
            )
            write_report(args.report, registry["version"], results, failures, len(papers))
            continue

        candidates = list(paper.get("download_candidates", []))
        candidates.append(f"https://doi.org/{paper['doi']}")
        discovery: dict = {}
        for name, discover in [
            ("pmc", lambda: discover_pmc_urls(session, paper["doi"])),
            ("crossref", lambda: discover_crossref_urls(session, paper["doi"])),
            ("doi", lambda: discover_doi_urls(session, paper["doi"])),
        ]:
            try:
                urls, info = discover()
                candidates.extend(urls)
                discovery[name] = info
            except Exception as exc:
                discovery[name] = {"error": f"{type(exc).__name__}: {exc}"}
        candidates.extend(discover_elsevier_urls(paper["doi"]))
        candidates = dedupe(candidates)

        attempts: list[dict] = []
        try:
            data, final_url, attempts = fetch_pdf(session, candidates)
            validation = validate_pdf(data, paper["expected_pages"])
        except Exception as exc:
            if isinstance(exc, DownloadError):
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
            write_report(args.report, registry["version"], results, failures, len(papers))
            print(json.dumps(failure, ensure_ascii=False, indent=2), flush=True)
            raise

        target.write_bytes(data)
        results.append(
            {
                "order": paper["order"],
                "key": key,
                "doi": paper["doi"],
                "path": str(target),
                "final_url": final_url,
                "sha256": sha256_bytes(data),
                "discovery": discovery,
                "attempts": attempts,
                **validation,
            }
        )
        write_report(args.report, registry["version"], results, failures, len(papers))
        print(
            json.dumps({"key": key, "pages": validation["pages"], "final_url": final_url}, ensure_ascii=False),
            flush=True,
        )
        time.sleep(1)

    print(json.dumps({"papers": len(results), "passed": len(results) == len(papers)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
