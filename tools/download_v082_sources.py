#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import fitz
import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/149 Safari/537.36"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_pdf(data: bytes, content_type: str = "") -> bool:
    return data.startswith(b"%PDF-") or "application/pdf" in content_type.lower()


def discover_pdf_urls(session: requests.Session, doi: str) -> list[str]:
    landing = f"https://doi.org/{doi}"
    response = session.get(landing, timeout=90, allow_redirects=True)
    response.raise_for_status()
    urls: list[str] = []
    ctype = response.headers.get("content-type", "")
    if is_pdf(response.content, ctype):
        return [response.url]
    soup = BeautifulSoup(response.text, "html.parser")
    for attr, value in [
        ("name", "citation_pdf_url"),
        ("name", "wkhealth_pdf_url"),
        ("property", "og:pdf"),
        ("name", "pdf_url"),
    ]:
        node = soup.find("meta", attrs={attr: value})
        if node and node.get("content"):
            urls.append(urljoin(response.url, node["content"]))
    for link in soup.find_all("a", href=True):
        href = urljoin(response.url, link["href"])
        label = " ".join(link.get_text(" ", strip=True).split()).lower()
        if any(token in href.lower() for token in ("/pdf/", ".pdf", "downloadpdf")) or "download pdf" in label or label == "pdf":
            urls.append(href)
    for match in re.findall(r'https?://[^"\'<> ]+(?:/pdf/[^"\'<> ]+|\.pdf(?:\?[^"\'<> ]*)?)', response.text):
        urls.append(match.replace("\\/", "/"))
    seen: set[str] = set()
    return [u for u in urls if not (u in seen or seen.add(u))]


def fetch_pdf(session: requests.Session, urls: list[str]) -> tuple[bytes, str, list[dict]]:
    attempts: list[dict] = []
    for url in urls:
        try:
            r = session.get(url, timeout=180, allow_redirects=True, headers={"Accept": "application/pdf,text/html;q=0.8,*/*;q=0.5"})
            ctype = r.headers.get("content-type", "")
            attempts.append({"url": url, "final_url": r.url, "status": r.status_code, "content_type": ctype, "bytes": len(r.content)})
            if r.ok and is_pdf(r.content, ctype) and len(r.content) > 10_000:
                return r.content, r.url, attempts
            if r.ok and "text/html" in ctype.lower():
                soup = BeautifulSoup(r.text, "html.parser")
                nested = []
                for node in soup.select('meta[name="citation_pdf_url"],meta[property="og:pdf"],a[href*=".pdf"],a[href*="/pdf/"]'):
                    href = node.get("content") or node.get("href")
                    if href:
                        nested.append(urljoin(r.url, href))
                for nurl in nested:
                    nr = session.get(nurl, timeout=180, allow_redirects=True, headers={"Accept": "application/pdf"})
                    nctype = nr.headers.get("content-type", "")
                    attempts.append({"url": nurl, "final_url": nr.url, "status": nr.status_code, "content_type": nctype, "bytes": len(nr.content)})
                    if nr.ok and is_pdf(nr.content, nctype) and len(nr.content) > 10_000:
                        return nr.content, nr.url, attempts
        except Exception as exc:
            attempts.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
    raise RuntimeError("all PDF download candidates failed")


def validate_pdf(data: bytes, expected_pages: int) -> dict:
    doc = fitz.open(stream=data, filetype="pdf")
    pages = len(doc)
    first_text = " ".join(doc[0].get_text("text").split()) if pages else ""
    if pages < max(5, expected_pages - 3):
        raise RuntimeError(f"downloaded PDF has {pages} pages, expected approximately {expected_pages}")
    return {"pages": pages, "first_page_text": first_text[:500]}


def main() -> None:
    p = argparse.ArgumentParser(description="Download and validate the official PDFs used by the V0.8.2 final reader build")
    p.add_argument("--registry", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--reuse", action="store_true")
    args = p.parse_args()

    registry = json.loads(args.registry.read_text("utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    results = []
    for paper in sorted(registry["papers"], key=lambda x: x["order"]):
        target = args.output_dir / f"{paper['order']:02d}_{paper['key']}.pdf"
        if args.reuse and target.exists():
            data = target.read_bytes()
            validation = validate_pdf(data, paper["expected_pages"])
            results.append({"key": paper["key"], "path": str(target), "source": "reused", "sha256": sha256_bytes(data), **validation})
            continue
        candidates = list(paper.get("download_candidates", []))
        doi_url = f"https://doi.org/{paper['doi']}"
        candidates.append(doi_url)
        try:
            candidates.extend(discover_pdf_urls(session, paper["doi"]))
        except Exception as exc:
            discovery_error = f"{type(exc).__name__}: {exc}"
        else:
            discovery_error = None
        deduped: list[str] = []
        for url in candidates:
            if url not in deduped:
                deduped.append(url)
        data, final_url, attempts = fetch_pdf(session, deduped)
        validation = validate_pdf(data, paper["expected_pages"])
        target.write_bytes(data)
        results.append({
            "key": paper["key"],
            "doi": paper["doi"],
            "path": str(target),
            "final_url": final_url,
            "sha256": sha256_bytes(data),
            "discovery_error": discovery_error,
            "attempts": attempts,
            **validation,
        })
        time.sleep(1)

    report = {"registry_version": registry["version"], "papers": results, "passed": len(results) == len(registry["papers"])}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"papers": len(results), "passed": report["passed"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
