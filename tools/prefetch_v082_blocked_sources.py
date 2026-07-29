#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import fitz
from curl_cffi import requests as curl_requests


BLOCKED_SOURCES = {
    "cho-2026": {
        "expected_title": "Pan-cancer spatial atlas of tertiary lymphoid structures",
        "landing_urls": [
            "https://www.science.org/doi/full/10.1126/science.adz2742",
            "https://doi.org/10.1126/science.adz2742",
        ],
        "pdf_urls": [
            "https://www.science.org/doi/pdf/10.1126/science.adz2742",
            "https://www.science.org/doi/pdf/10.1126/science.adz2742?download=true",
            "https://www.science.org/doi/epdf/10.1126/science.adz2742",
            "https://www.science.org/action/showPdf?doi=10.1126%2Fscience.adz2742",
            "https://science.sciencemag.org/content/392/6801/eadz2742.full.pdf",
            "https://science.sciencemag.org/content/sci/392/6801/eadz2742.full.pdf",
        ],
    }
}


def validate_pdf(data: bytes, expected_pages: int, expected_title: str) -> dict:
    if not data.startswith(b"%PDF-"):
        raise RuntimeError("response is not a PDF")
    document = fitz.open(stream=data, filetype="pdf")
    pages = len(document)
    if pages != expected_pages:
        raise RuntimeError(f"page count mismatch: {pages} != {expected_pages}")
    first_text = " ".join(document[0].get_text("text").split())
    second_text = " ".join(document[1].get_text("text").split()) if pages > 1 else ""
    searchable = (first_text + " " + second_text).lower()
    if expected_title.lower() not in searchable:
        raise RuntimeError("expected article title not found on first two pages")
    return {
        "pages": pages,
        "first_page_text": first_text[:600],
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def fetch_with_profile(profile: str, landing_urls: list[str], pdf_urls: list[str]) -> tuple[bytes, str, list[dict]]:
    attempts: list[dict] = []
    session = curl_requests.Session(impersonate=profile)
    common_headers = {
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    }
    referer = landing_urls[0]
    for landing in landing_urls:
        try:
            response = session.get(landing, headers={**common_headers, "Accept": "text/html,application/xhtml+xml"}, timeout=90, allow_redirects=True)
            attempts.append({
                "profile": profile,
                "kind": "landing",
                "url": landing,
                "status": response.status_code,
                "final_url": response.url,
                "content_type": response.headers.get("content-type", ""),
                "bytes": len(response.content),
            })
            if response.status_code < 400:
                referer = response.url
        except Exception as exc:
            attempts.append({"profile": profile, "kind": "landing", "url": landing, "error": f"{type(exc).__name__}: {exc}"})

    for pdf_url in pdf_urls:
        try:
            response = session.get(
                pdf_url,
                headers={
                    **common_headers,
                    "Accept": "application/pdf,application/octet-stream;q=0.9,text/html;q=0.7,*/*;q=0.5",
                    "Referer": referer,
                    "Sec-Fetch-Site": "same-origin",
                },
                timeout=180,
                allow_redirects=True,
            )
            content_type = response.headers.get("content-type", "")
            attempts.append({
                "profile": profile,
                "kind": "pdf",
                "url": pdf_url,
                "status": response.status_code,
                "final_url": response.url,
                "content_type": content_type,
                "bytes": len(response.content),
                "content_disposition": response.headers.get("content-disposition", ""),
            })
            if response.content.startswith(b"%PDF-") and len(response.content) > 100_000:
                return response.content, response.url, attempts
        except Exception as exc:
            attempts.append({"profile": profile, "kind": "pdf", "url": pdf_url, "error": f"{type(exc).__name__}: {exc}"})
    raise RuntimeError(json.dumps(attempts, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Prefetch publisher PDFs that require a real browser TLS fingerprint")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    registry = json.loads(args.registry.read_text("utf-8"))
    papers = {paper["key"]: paper for paper in registry["papers"]}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {"papers": [], "passed": True}

    for key, source in BLOCKED_SOURCES.items():
        paper = papers[key]
        target = args.output_dir / f"{paper['order']:02d}_{key}.pdf"
        if target.exists():
            try:
                validation = validate_pdf(target.read_bytes(), paper["expected_pages"], source["expected_title"])
                report["papers"].append({"key": key, "status": "reused", "path": str(target), **validation})
                continue
            except Exception:
                target.unlink()

        all_attempts: list[dict] = []
        data = None
        final_url = None
        for profile in ["chrome", "chrome120", "chrome119", "safari", "safari17_0"]:
            try:
                data, final_url, attempts = fetch_with_profile(profile, source["landing_urls"], source["pdf_urls"])
                all_attempts.extend(attempts)
                break
            except Exception as exc:
                try:
                    all_attempts.extend(json.loads(str(exc)))
                except Exception:
                    all_attempts.append({"profile": profile, "error": f"{type(exc).__name__}: {exc}"})

        if data is None or final_url is None:
            report["papers"].append({"key": key, "status": "failed", "attempts": all_attempts})
            report["passed"] = False
            continue

        validation = validate_pdf(data, paper["expected_pages"], source["expected_title"])
        target.write_bytes(data)
        report["papers"].append({
            "key": key,
            "status": "downloaded",
            "path": str(target),
            "final_url": final_url,
            "attempts": all_attempts,
            **validation,
        })

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
