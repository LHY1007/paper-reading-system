#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


STUDY_SELECTORS = [
    ".figure-study-button",
    ".v081-study-open",
    ".v082-study-launch",
    "#viewerStudyLaunchV077",
    "#v6StudyLaunch",
]


def apply(html: str, manifest: dict[str, Any]) -> str:
    soup = BeautifulSoup(html, "html.parser")
    profile = manifest.get("reader_profile") or {}
    name = str(profile.get("name") or "legacy")
    enabled = profile.get("figure_study_enabled") is not False
    if soup.body:
        soup.body["data-reader-profile"] = name
        soup.body["data-figure-study-enabled"] = "true" if enabled else "false"
    if not enabled:
        for selector in STUDY_SELECTORS:
            for node in soup.select(selector):
                node["hidden"] = ""
                node["aria-hidden"] = "true"
                style = str(node.get("style") or "")
                compact = style.replace(" ", "").lower()
                if "display:none" not in compact:
                    node["style"] = (style.rstrip(";") + ";display:none!important").lstrip(";")
        review = soup.find("script", id="v080ReviewManifest")
        if review:
            try:
                data = json.loads(review.get_text() or "{}")
            except json.JSONDecodeError:
                data = {}
            expected = data.setdefault("expected", {})
            expected["study_buttons"] = 0
            expected["study_ids"] = []
            data["reader_profile"] = profile
            review["type"] = "application/json"
            review.string = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return str(soup)


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply V0.8.3 profile-specific visibility without changing the frozen reader layout")
    parser.add_argument("html", type=Path)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text("utf-8"))
    args.html.write_text(apply(args.html.read_text("utf-8"), manifest), "utf-8")
    print(json.dumps({"html": str(args.html), "reader_profile": manifest.get("reader_profile")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
