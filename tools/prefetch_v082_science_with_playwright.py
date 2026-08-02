#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import BrowserContext, Page, Response, sync_playwright

import download_v082_sources as source_tools


PDF_MAGIC = b"%PDF-"


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def write_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


def response_payload(response: Response | None) -> tuple[bytes | None, dict]:
    if response is None:
        return None, {"error": "navigation returned no response"}
    record = {
        "url": response.url,
        "status": response.status,
        "content_type": response.headers.get("content-type", ""),
    }
    try:
        body = response.body()
        record["bytes"] = len(body)
        if body.startswith(PDF_MAGIC):
            return body, record
        record["prefix"] = body[:160].decode("utf-8", errors="replace")
    except Exception as exc:
        record["body_error"] = f"{type(exc).__name__}: {exc}"
    return None, record


def candidate_urls(doi: str) -> list[str]:
    escaped = quote(doi, safe="/")
    return [
        f"https://www.science.org/doi/pdf/{escaped}",
        f"https://www.science.org/doi/pdf/{escaped}?download=true",
        f"https://www.science.org/doi/epdf/{escaped}",
        f"https://www.science.org/doi/{escaped}",
    ]


def stealth_context(browser) -> BrowserContext:
    return browser.new_context(
        accept_downloads=True,
        locale="en-US",
        timezone_id="America/New_York",
        viewport={"width": 1440, "height": 1100},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/149.0.0.0 Safari/537.36"
        ),
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Site": "same-origin",
            "Upgrade-Insecure-Requests": "1",
        },
    )


def prepare_page(page: Page) -> None:
    page.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        window.chrome = window.chrome || {runtime: {}};
        """
    )


def attempt_browser_fetch(doi: str, timeout_ms: int) -> tuple[bytes | None, list[dict]]:
    attempts: list[dict] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        context = stealth_context(browser)
        page = context.new_page()
        prepare_page(page)

        # Establish first-party cookies and execute any JavaScript challenge before
        # requesting the article or PDF endpoint.
        for warmup in ("https://www.science.org/", f"https://www.science.org/doi/{doi}"):
            try:
                response = page.goto(warmup, wait_until="domcontentloaded", timeout=timeout_ms)
                _, record = response_payload(response)
                record["kind"] = "warmup_navigation"
                record["title"] = norm(page.title())
                attempts.append(record)
                page.wait_for_timeout(5000)
                for selector in (
                    "button#onetrust-accept-btn-handler",
                    "button:has-text('Accept All Cookies')",
                    "button:has-text('Accept')",
                ):
                    try:
                        if page.locator(selector).first.is_visible(timeout=500):
                            page.locator(selector).first.click(timeout=1000)
                            break
                    except Exception:
                        pass
            except Exception as exc:
                attempts.append({
                    "kind": "warmup_navigation",
                    "url": warmup,
                    "error": f"{type(exc).__name__}: {exc}",
                })

        for url in candidate_urls(doi):
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                body, record = response_payload(response)
                record["kind"] = "browser_navigation"
                record["title"] = norm(page.title())
                attempts.append(record)
                if body:
                    browser.close()
                    return body, attempts
            except Exception as exc:
                attempts.append({
                    "kind": "browser_navigation",
                    "url": url,
                    "error": f"{type(exc).__name__}: {exc}",
                })

            # Use Playwright's APIRequestContext after navigation so all first-party
            # cookies and browser headers are retained.
            try:
                api_response = context.request.get(
                    url,
                    headers={"Referer": f"https://www.science.org/doi/{doi}"},
                    timeout=timeout_ms,
                    fail_on_status_code=False,
                )
                body = api_response.body()
                record = {
                    "kind": "browser_context_request",
                    "url": api_response.url,
                    "status": api_response.status,
                    "content_type": api_response.headers.get("content-type", ""),
                    "bytes": len(body),
                }
                attempts.append(record)
                if body.startswith(PDF_MAGIC):
                    browser.close()
                    return body, attempts
            except Exception as exc:
                attempts.append({
                    "kind": "browser_context_request",
                    "url": url,
                    "error": f"{type(exc).__name__}: {exc}",
                })

        browser.close()
    return None, attempts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch a publisher-blocked Science PDF using a real Chromium session and validate it before caching"
    )
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--key", default="cho-2026")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--timeout-ms", type=int, default=90000)
    args = parser.parse_args()

    registry = json.loads(args.registry.read_text("utf-8"))
    paper = next(item for item in registry["papers"] if item["key"] == args.key)
    target = args.output_dir / f"{int(paper['order']):02d}_{paper['key']}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        data = target.read_bytes()
        try:
            validation = source_tools.validate_pdf(data, int(paper["expected_pages"]))
            write_report(args.report, {
                "key": args.key,
                "status": "reused",
                "path": str(target),
                "sha256": hashlib.sha256(data).hexdigest(),
                **validation,
                "passed": True,
            })
            return
        except Exception:
            target.unlink(missing_ok=True)

    data, attempts = attempt_browser_fetch(paper["doi"], args.timeout_ms)
    if data is None:
        write_report(args.report, {
            "key": args.key,
            "status": "failed",
            "attempts": attempts,
            "passed": False,
        })
        raise SystemExit(1)

    validation = source_tools.validate_pdf(data, int(paper["expected_pages"]))
    target.write_bytes(data)
    write_report(args.report, {
        "key": args.key,
        "status": "downloaded",
        "path": str(target),
        "sha256": hashlib.sha256(data).hexdigest(),
        "attempts": attempts,
        **validation,
        "passed": True,
    })


if __name__ == "__main__":
    main()
