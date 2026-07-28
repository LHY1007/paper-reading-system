#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import socket
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextlib.contextmanager
def serve(root: Path):
    port = free_port()
    handler = partial(QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def attr(page: Page, selector: str, name: str) -> str | None:
    return page.locator(selector).get_attribute(name)


def visible(page: Page, selector: str) -> bool:
    return page.locator(selector).count() > 0 and page.locator(selector).is_visible()


def test_reader(page: Page, url: str, name: str) -> dict[str, Any]:
    page_errors: list[str] = []
    console_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.goto(url, wait_until="load")
    page.wait_for_timeout(1200)

    checks: dict[str, Any] = {}
    failures: list[str] = []

    def require(condition: bool, label: str, detail: Any = None) -> None:
        checks[label] = {"passed": bool(condition), "detail": detail}
        if not condition:
            failures.append(label)

    runtime_review = page.evaluate("window.__CANVAS_V080_REVIEW__ || null")
    require(attr(page, "html", "data-v080-review") == "passed", "v080_review_passed", runtime_review)
    require(page.locator("#quick-pane").count() == 1 and page.locator("#bilingual-pane").count() == 1, "both_mode_panes_exist")
    mode_count = page.locator(".mode-btn[data-mode]").count()
    require(mode_count >= 2, "visible_mode_controls_exist", mode_count)
    if mode_count >= 2:
        quick = page.locator('.mode-btn[data-mode="quick"]').first
        bilingual = page.locator('.mode-btn[data-mode="bilingual"]').first
        quick.click()
        page.wait_for_timeout(150)
        require(attr(page, "body", "data-mode") == "quick" and page.locator("#quick-pane").evaluate("e=>e.classList.contains('active')"), "quick_mode_switch")
        require(quick.get_attribute("aria-pressed") == "true", "quick_mode_accessibility_state")
        bilingual.click()
        page.wait_for_timeout(150)
        require(attr(page, "body", "data-mode") == "bilingual" and page.locator("#bilingual-pane").evaluate("e=>e.classList.contains('active')"), "bilingual_mode_switch")
        require(bilingual.get_attribute("aria-pressed") == "true", "bilingual_mode_accessibility_state")

    page.locator("#settingsBtn").click()
    page.wait_for_timeout(100)
    require(page.locator("#settings").evaluate("e=>e.classList.contains('open')"), "settings_open")
    require(visible(page, "#settingsBackdrop"), "settings_backdrop_visible")
    page.locator("#settingsBackdrop").click(position={"x": 2, "y": 2})
    page.wait_for_timeout(100)
    require(not page.locator("#settings").evaluate("e=>e.classList.contains('open')"), "settings_outside_close")

    toggle = page.locator(".figure-card .card-toggle").first
    card_id = toggle.get_attribute("data-card")
    content = page.locator(f"#{card_id} > .figure-content")
    before_hidden = content.get_attribute("hidden") is not None
    toggle.click()
    page.wait_for_timeout(150)
    after_hidden = content.get_attribute("hidden") is not None
    require(before_hidden and not after_hidden and toggle.get_attribute("aria-expanded") == "true", "figure_card_toggle", {"id": card_id, "before_hidden": before_hidden, "after_hidden": after_hidden})

    viewer_button = page.locator(".figure-card .open-in-viewer").first
    target = viewer_button.get_attribute("data-target")
    viewer_button.click()
    page.wait_for_timeout(250)
    require(page.locator("body").evaluate("e=>e.classList.contains('viewer-open')") and attr(page, "#viewer", "aria-hidden") == "false", "right_viewer_open", target)
    require(bool(page.locator("#viewerContent").inner_text().strip()), "right_viewer_has_content")
    if page.locator("#viewerClose").count():
        page.locator("#viewerClose").click()
        page.wait_for_timeout(100)
        require(not page.locator("body").evaluate("e=>e.classList.contains('viewer-open')"), "right_viewer_close")

    study_button = page.locator(".figure-study-button").first
    if study_button.count():
        study_id = study_button.get_attribute("data-figure-id")
        study_button.click()
        page.wait_for_timeout(450)
        require(page.locator("#v6Study").count() == 1 and attr(page, "#v6Study", "aria-hidden") == "false" and page.locator("body").evaluate("e=>e.classList.contains('v6-study-open')"), "figure_study_open", study_id)
        require(bool(page.locator("#v6StudyDoc").inner_text().strip()) if page.locator("#v6StudyDoc").count() else False, "figure_study_has_content")
        if page.locator("#v6StudyClose").count():
            page.locator("#v6StudyClose").click()
            page.wait_for_timeout(120)
            closed = attr(page, "#v6Study", "aria-hidden") == "true" and not page.locator("#v6Study").evaluate("e=>e.classList.contains('open')") and not page.locator("body").evaluate("e=>e.classList.contains('v6-study-open')")
            require(closed, "figure_study_close", {"aria_hidden": attr(page, "#v6Study", "aria-hidden"), "class": attr(page, "#v6Study", "class")})

    if page.locator(".term-pop").count():
        page.locator(".term-pop").first.click()
        page.wait_for_timeout(120)
        require(page.locator("#termTooltip").evaluate("e=>e.classList.contains('show')") and bool(page.locator("#termTooltip").inner_text().strip()), "term_tooltip_content", page.locator("#termTooltip").inner_text())
        page.locator("body").click(position={"x": 5, "y": 5})

    if page.locator(".citation").count():
        page.locator(".citation").first.click()
        page.wait_for_timeout(120)
        require(attr(page, "#referencePop", "hidden") is None and bool(page.locator("#referencePop").inner_text().strip()), "citation_popover_content", page.locator("#referencePop").inner_text()[:240])

    require(page.locator("#v6AnnotationBtn").count() == 1, "dynamic_annotation_tool_installed")
    require(page.locator("#v6EditBtn").count() == 1, "dynamic_edit_tool_installed")
    require(not page_errors, "no_page_errors", page_errors)
    require(not console_errors, "no_console_errors", console_errors)

    return {
        "file": name,
        "url": url,
        "runtime_review": runtime_review,
        "checks": checks,
        "page_errors": page_errors,
        "console_errors": console_errors,
        "failures": failures,
        "passed": not failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Browser regression for the exact V0.8.2 CANVAS reader")
    parser.add_argument("html", nargs="+", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    reports = []
    with serve(root) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for path in args.html:
                absolute = path.resolve()
                relative = absolute.relative_to(root).as_posix()
                page = browser.new_page(viewport={"width": 1920, "height": 1080})
                reports.append(test_reader(page, f"{base_url}/{relative}", path.name))
                page.close()
        finally:
            browser.close()
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": reports,
        "passed": all(item["passed"] for item in reports),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"] and not args.diagnostic:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
