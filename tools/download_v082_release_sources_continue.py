#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import requests

import download_v082_release_sources as release


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit CANVAS and download every available non-CANVAS PDF without stopping at the first failed source"
    )
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
        canonical = release.locate_canonical(args.canonical_html)
        results.append(release.audit_canonical(canonical, papers[0]))
    except Exception as exc:
        failures.append({
            "order": 0,
            "key": papers[0].get("key", "canvas"),
            "error": f"{type(exc).__name__}: {exc}",
        })
        release.write_report(args.report, registry["version"], len(papers), results, failures)
        raise

    session = requests.Session()
    session.headers.update({"User-Agent": release.source_tools.UA})
    for paper in papers[1:]:
        key = paper["key"]
        target = args.output_dir / f"{paper['order']:02d}_{key}.pdf"
        print(f"===== SOURCE {paper['order']:02d} {key} =====", flush=True)

        if args.reuse and target.exists():
            try:
                data = target.read_bytes()
                validation = release.source_tools.validate_pdf(data, paper["expected_pages"])
                results.append({
                    "order": paper["order"],
                    "key": key,
                    "doi": paper["doi"],
                    "source_mode": "reused_pdf",
                    "path": str(target),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    **validation,
                })
                release.write_report(args.report, registry["version"], len(papers), results, failures)
                continue
            except Exception as exc:
                target.unlink(missing_ok=True)
                print(f"invalid cached PDF for {key}: {type(exc).__name__}: {exc}", flush=True)

        candidates, discovery = release.discover_candidates(session, paper)
        attempts: list[dict] = []
        try:
            data, final_url, attempts = release.release_fetch_pdf(session, candidates)
            validation = release.source_tools.validate_pdf(data, paper["expected_pages"])
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
            print(json.dumps({"key": key, "pages": validation["pages"], "final_url": final_url}, ensure_ascii=False), flush=True)
        except Exception as exc:
            if isinstance(exc, release.source_tools.DownloadError):
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
            print(json.dumps(failure, ensure_ascii=False, indent=2), flush=True)
        finally:
            release.write_report(args.report, registry["version"], len(papers), results, failures)
        time.sleep(1)

    release.write_report(args.report, registry["version"], len(papers), results, failures)
    summary = {
        "completed": len(results),
        "expected": len(papers),
        "failed_keys": [failure["key"] for failure in failures],
        "passed": len(results) == len(papers) and not failures,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
