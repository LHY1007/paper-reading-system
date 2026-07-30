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


VIEWPORTS = [
    {"name": "desktop-1920", "width": 1920, "height": 1080},
    {"name": "laptop-1366", "width": 1366, "height": 768},
]

FIXED_SELECTORS = [
    "#topbar",
    ".mode-btn[data-mode='quick']",
    ".mode-btn[data-mode='bilingual']",
    "#settingsBtn",
    "#settings",
    "#settingsBackdrop",
    "#viewer",
    "#viewerClose",
    "#v6Study",
    "#v6StudyClose",
    "#quick-pane",
    "#bilingual-pane",
    "#figure-table-index",
]

STYLE_PROPERTIES = [
    "position",
    "display",
    "box-sizing",
    "font-family",
    "font-size",
    "font-weight",
    "line-height",
    "color",
    "background-color",
    "border-top-color",
    "border-right-color",
    "border-bottom-color",
    "border-left-color",
    "border-radius",
    "padding-top",
    "padding-right",
    "padding-bottom",
    "padding-left",
    "gap",
    "z-index",
    "overflow-x",
    "overflow-y",
]

GEOMETRY_SELECTORS = {
    "#topbar": ["x", "y", "width", "height"],
    ".mode-btn[data-mode='quick']": ["height"],
    ".mode-btn[data-mode='bilingual']": ["height"],
    "#settingsBtn": ["height"],
    "#quick-pane": ["x", "width"],
    "#bilingual-pane": ["x", "width"],
}


def snapshot(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """({selectors, properties}) => {
            const result = {selectors: {}, rootVars: {}};
            const rootStyle = getComputedStyle(document.documentElement);
            for (const name of rootStyle) {
                if (name.startsWith('--')) result.rootVars[name] = rootStyle.getPropertyValue(name).trim();
            }
            for (const selector of selectors) {
                const element = document.querySelector(selector);
                if (!element) {
                    result.selectors[selector] = null;
                    continue;
                }
                const style = getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                const values = {};
                for (const prop of properties) values[prop] = style.getPropertyValue(prop);
                result.selectors[selector] = {
                    tag: element.tagName,
                    classes: [...element.classList],
                    styles: values,
                    rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
                };
            }
            return result;
        }""",
        {"selectors": FIXED_SELECTORS, "properties": STYLE_PROPERTIES},
    )


def rounded(value: float) -> float:
    return round(float(value), 2)


def compare_snapshot(base: dict[str, Any], candidate: dict[str, Any], viewport: str, file_name: str) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if base.get("rootVars") != candidate.get("rootVars"):
        differing = sorted(
            key for key in set(base.get("rootVars", {})) | set(candidate.get("rootVars", {}))
            if base.get("rootVars", {}).get(key) != candidate.get("rootVars", {}).get(key)
        )
        errors.append({
            "file": file_name,
            "viewport": viewport,
            "selector": ":root",
            "issue": "CSS custom properties changed",
            "properties": differing[:50],
        })
    for selector in FIXED_SELECTORS:
        left = base.get("selectors", {}).get(selector)
        right = candidate.get("selectors", {}).get(selector)
        if left is None or right is None:
            if left != right or left is None:
                errors.append({
                    "file": file_name,
                    "viewport": viewport,
                    "selector": selector,
                    "issue": "fixed shell selector missing",
                    "baseline_present": left is not None,
                    "candidate_present": right is not None,
                })
            continue
        if left.get("tag") != right.get("tag") or left.get("classes") != right.get("classes"):
            errors.append({
                "file": file_name,
                "viewport": viewport,
                "selector": selector,
                "issue": "fixed shell element tag/classes changed",
                "baseline": {"tag": left.get("tag"), "classes": left.get("classes")},
                "candidate": {"tag": right.get("tag"), "classes": right.get("classes")},
            })
        style_diff = {
            prop: {"baseline": left["styles"].get(prop), "candidate": right["styles"].get(prop)}
            for prop in STYLE_PROPERTIES
            if left["styles"].get(prop) != right["styles"].get(prop)
        }
        if style_diff:
            errors.append({
                "file": file_name,
                "viewport": viewport,
                "selector": selector,
                "issue": "computed fixed-shell styles changed",
                "differences": style_diff,
            })
        for field in GEOMETRY_SELECTORS.get(selector, []):
            tolerance = 2.0
            lv = float(left["rect"][field])
            rv = float(right["rect"][field])
            if abs(lv - rv) > tolerance:
                errors.append({
                    "file": file_name,
                    "viewport": viewport,
                    "selector": selector,
                    "issue": f"fixed-shell geometry changed: {field}",
                    "baseline": rounded(lv),
                    "candidate": rounded(rv),
                    "tolerance": tolerance,
                })
    return errors


def load_snapshot(page: Page, url: str) -> dict[str, Any]:
    page.goto(url, wait_until="load")
    page.wait_for_timeout(800)
    page.evaluate("localStorage.clear(); sessionStorage.clear();")
    page.reload(wait_until="load")
    page.wait_for_timeout(800)
    return snapshot(page)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify visual/layout invariance of fixed V0.8.2 product chrome")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("readers", nargs="+", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    files = [args.baseline, *args.readers]
    for path in files:
        path.resolve().relative_to(root)
    errors: list[dict[str, Any]] = []
    with serve(root) as base_url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for viewport in VIEWPORTS:
                context = browser.new_context(viewport={"width": viewport["width"], "height": viewport["height"]})
                try:
                    baseline_page = context.new_page()
                    baseline_rel = args.baseline.resolve().relative_to(root).as_posix()
                    baseline_snapshot = load_snapshot(baseline_page, f"{base_url}/{baseline_rel}")
                    baseline_page.close()
                    for path in args.readers:
                        page = context.new_page()
                        relative = path.resolve().relative_to(root).as_posix()
                        candidate_snapshot = load_snapshot(page, f"{base_url}/{relative}")
                        page.close()
                        errors.extend(compare_snapshot(baseline_snapshot, candidate_snapshot, viewport["name"], path.name))
                finally:
                    context.close()
        finally:
            browser.close()
    report = {
        "version": "v082-browser-layout-invariance-1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline": args.baseline.name,
        "readers": [path.name for path in args.readers],
        "viewports": VIEWPORTS,
        "fixed_selectors": FIXED_SELECTORS,
        "style_properties": STYLE_PROPERTIES,
        "error_count": len(errors),
        "errors": errors,
        "passed": not errors,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
