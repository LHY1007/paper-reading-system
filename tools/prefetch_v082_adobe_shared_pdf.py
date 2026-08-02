#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import fitz
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import Response, sync_playwright

PDF_MAGIC = b"%PDF-"


def write_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


def validate(data: bytes, *, expected_pages: int, doi: str, title_fragment: str) -> dict:
    if not data.startswith(PDF_MAGIC):
        raise RuntimeError("downloaded payload is not a PDF")
    document = fitz.open(stream=data, filetype="pdf")
    try:
        pages = document.page_count
        if pages != expected_pages:
            raise RuntimeError(f"page count mismatch: {pages} != {expected_pages}")
        sample_pages = sorted(set([0, 1, max(0, pages // 2), pages - 1]))
        sample_text = "\n".join(document.load_page(index).get_text("text") for index in sample_pages)
        normalized = re.sub(r"\s+", " ", sample_text).lower()
        if doi.lower() not in normalized:
            # DOI metadata is authoritative when text extraction splits punctuation.
            metadata = " ".join(str(value or "") for value in document.metadata.values()).lower()
            xref_text = ""
            try:
                xref_text = document.xref_object(document.pdf_catalog()).lower()
            except Exception:
                pass
            if doi.lower() not in metadata and doi.lower() not in xref_text:
                raise RuntimeError("expected DOI was not found in sampled text or PDF metadata")
        title_tokens = [token.lower() for token in re.findall(r"[A-Za-z]{5,}", title_fragment)[:5]]
        if title_tokens and sum(token in normalized for token in title_tokens) < min(3, len(title_tokens)):
            raise RuntimeError("expected title was not found in sampled text")
        return {
            "pages": pages,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "metadata": document.metadata,
        }
    finally:
        document.close()


def direct_candidates(url: str) -> tuple[list[str], list[dict]]:
    attempts: list[dict] = []
    candidates = [url]
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/149.0.0.0 Safari/537.36",
        "Accept": "application/pdf,text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    })
    try:
        response = session.get(url, allow_redirects=True, timeout=60)
        record = {
            "kind": "requests",
            "requested_url": url,
            "final_url": response.url,
            "status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "bytes": len(response.content),
        }
        attempts.append(record)
        if response.content.startswith(PDF_MAGIC):
            return ["DATA:" + response.content.hex()], attempts
        if response.ok and "html" in record["content_type"].lower():
            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup.find_all(["a", "iframe", "embed", "object", "meta"]):
                raw_values = [tag.get("href"), tag.get("src"), tag.get("data"), tag.get("content")]
                for raw in raw_values:
                    if not raw:
                        continue
                    for possible in re.findall(r"https?://[^\s\"'<>]+|/[^\s\"'<>]+", raw):
                        absolute = urljoin(response.url, possible)
                        if absolute not in candidates and (
                            "acrobat.adobe.com" in absolute
                            or "documentcloud.adobe.com" in absolute
                            or ".pdf" in absolute.lower()
                            or "aaid" in absolute.lower()
                        ):
                            candidates.append(absolute)
    except Exception as exc:
        attempts.append({"kind": "requests", "url": url, "error": f"{type(exc).__name__}: {exc}"})
    return candidates, attempts


def browser_fetch(urls: list[str], timeout_ms: int) -> tuple[bytes | None, list[dict]]:
    attempts: list[dict] = []
    captured: list[tuple[str, bytes, str, int]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            accept_downloads=True,
            locale="en-US",
            viewport={"width": 1440, "height": 1000},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/149.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

        def on_response(response: Response) -> None:
            content_type = response.headers.get("content-type", "")
            if "pdf" not in content_type.lower() and ".pdf" not in response.url.lower():
                return
            try:
                body = response.body()
            except Exception:
                return
            attempts.append({
                "kind": "network_response",
                "url": response.url,
                "status": response.status,
                "content_type": content_type,
                "bytes": len(body),
            })
            if body.startswith(PDF_MAGIC):
                captured.append((response.url, body, content_type, response.status))

        page.on("response", on_response)
        for url in urls:
            if url.startswith("DATA:"):
                browser.close()
                return bytes.fromhex(url[5:]), attempts
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                attempts.append({
                    "kind": "navigation",
                    "requested_url": url,
                    "final_url": page.url,
                    "status": response.status if response else None,
                    "title": page.title(),
                })
                page.wait_for_timeout(12000)
                if captured:
                    browser.close()
                    return max(captured, key=lambda item: len(item[1]))[1], attempts

                selectors = [
                    "button[aria-label*='Download' i]",
                    "button[title*='Download' i]",
                    "a[download]",
                    "text=Download",
                ]
                for selector in selectors:
                    try:
                        locator = page.locator(selector).first
                        if not locator.is_visible(timeout=700):
                            continue
                        with page.expect_download(timeout=15000) as download_info:
                            locator.click(timeout=3000)
                        download = download_info.value
                        path = download.path()
                        if path:
                            data = Path(path).read_bytes()
                            attempts.append({
                                "kind": "browser_download",
                                "url": download.url,
                                "suggested_filename": download.suggested_filename,
                                "bytes": len(data),
                            })
                            if data.startswith(PDF_MAGIC):
                                browser.close()
                                return data, attempts
                    except Exception as exc:
                        attempts.append({
                            "kind": "download_click",
                            "selector": selector,
                            "error": f"{type(exc).__name__}: {exc}",
                        })
            except Exception as exc:
                attempts.append({"kind": "navigation", "url": url, "error": f"{type(exc).__name__}: {exc}"})

        browser.close()
    return None, attempts


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize a temporary Adobe Acrobat shared PDF into an audited local source cache")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-pages", type=int, required=True)
    parser.add_argument("--doi", required=True)
    parser.add_argument("--title-fragment", required=True)
    parser.add_argument("--timeout-ms", type=int, default=90000)
    args = parser.parse_args()

    if args.output.exists():
        try:
            data = args.output.read_bytes()
            result = validate(
                data,
                expected_pages=args.expected_pages,
                doi=args.doi,
                title_fragment=args.title_fragment,
            )
            write_report(args.report, {"status": "reused", "path": str(args.output), "passed": True, **result})
            return
        except Exception:
            args.output.unlink(missing_ok=True)

    candidates, direct_attempts = direct_candidates(args.url)
    if candidates and candidates[0].startswith("DATA:"):
        data = bytes.fromhex(candidates[0][5:])
        browser_attempts: list[dict] = []
    else:
        data, browser_attempts = browser_fetch(candidates, args.timeout_ms)
    attempts = direct_attempts + browser_attempts
    if data is None:
        write_report(args.report, {"status": "failed", "passed": False, "attempts": attempts, "candidates": candidates})
        raise SystemExit(1)

    result = validate(
        data,
        expected_pages=args.expected_pages,
        doi=args.doi,
        title_fragment=args.title_fragment,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    write_report(args.report, {
        "status": "downloaded",
        "path": str(args.output),
        "passed": True,
        "source_url": args.url,
        "attempts": attempts,
        **result,
    })


if __name__ == "__main__":
    main()
