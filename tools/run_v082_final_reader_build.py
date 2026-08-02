#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command), flush=True)
    result = subprocess.run(command, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}")
    return result


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text("utf-8"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sequential fail-closed V0.8.2 final reader build")
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("final/V0.8.2"))
    parser.add_argument("--build-root", type=Path, default=Path(".build/v082"))
    parser.add_argument("--registry", type=Path, default=Path("config/v082_paper_sources.json"))
    parser.add_argument("--schema", type=Path, default=Path("schemas/paper_content_manifest_v082.schema.json"))
    parser.add_argument("--shell-lock", type=Path, default=Path("config/v082_frozen_shell_lock.json"))
    parser.add_argument("--minimum-reader-score", type=float, default=30.0)
    args = parser.parse_args()

    root = Path(".")
    output = args.output_root
    reports = output / "reports"
    readers = output / "readers"
    manifests = output / "manifests"
    tasks = output / "tasks"
    audits = output / "audits"
    evidence = args.build_root / "final-evidence"
    templates = args.build_root / "templates"

    for path in (readers, manifests, tasks, audits, evidence, templates):
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)

    registry = load(args.registry)
    ordered = sorted(registry["papers"], key=lambda item: item["order"])
    canvas = next(item for item in ordered if item["order"] == 0)
    master = readers / canvas["output"]
    shell = templates / "V082_CANVAS_FROZEN_SHELL.html"

    run([
        sys.executable,
        "tools/normalize_v082_canvas_master.py",
        str(args.canonical),
        str(master),
        "--report",
        str(reports / "NORMALIZED_MASTER.json"),
    ])
    run([
        sys.executable,
        "tools/validate_v082_canvas_shell_lock.py",
        str(master),
        "--canonical",
        str(master),
        "--report",
        str(reports / "00_CANVAS_SHELL.json"),
    ])
    run([
        sys.executable,
        "tools/validate_v082_canvas_components.py",
        str(master),
        "--report",
        str(reports / "00_CANVAS_COMPONENTS.json"),
    ])
    run([
        sys.executable,
        "tools/validate_reader_content_coverage.py",
        str(master),
        "--baseline",
        str(args.canonical),
        "--report",
        str(reports / "00_CANVAS_CONTENT.json"),
    ])
    run([
        sys.executable,
        "tools/audit_v082_reader_experience_v2.py",
        str(args.canonical),
        str(master),
        "--json",
        str(reports / "00_CANVAS_READER_EXPERIENCE.json"),
        "--md",
        str(reports / "00_CANVAS_READER_EXPERIENCE.md"),
        "--minimum-score",
        str(args.minimum_reader_score),
    ])
    run([
        sys.executable,
        "tools/freeze_v082_canvas_shell_v2.py",
        str(master),
        str(shell),
        "--report",
        str(reports / "FROZEN_SHELL_BUILD.json"),
    ])
    run([
        sys.executable,
        "tools/validate_v082_frozen_shell.py",
        str(shell),
        "--master",
        str(master),
        "--lock",
        str(args.shell_lock),
        "--report",
        str(reports / "FROZEN_SHELL_GATE.json"),
    ])

    statuses: list[dict[str, Any]] = []
    build_error: str | None = None
    for paper in ordered:
        if paper["order"] == 0:
            continue
        key = paper["key"]
        order = int(paper["order"])
        prefix = f"{order:02d}_{key}"
        print(f"\n===== FINAL SEQUENTIAL BUILD {prefix} =====", flush=True)
        pdf = args.pdf_dir / f"{order:02d}_{key}.pdf"
        raw = evidence / f"{key}.json"
        audit = audits / f"{key}.json"
        task = tasks / f"{key}.json"
        manifest = manifests / f"{key}.json"
        reader = readers / paper["output"]
        status_path = reports / f"{prefix}_BUILD_READINESS.json"

        if not pdf.exists():
            status = {
                "version": "v082-reader-build-readiness-1",
                "paper_key": key,
                "rendered": False,
                "reason": "exact source PDF is missing",
                "expected_path": str(pdf),
            }
            write(status_path, status)
            statuses.append(status)
            build_error = status["reason"]
            break

        parser_result = run([
            sys.executable,
            "tools/build_pdf_native_manifest_v082.py",
            str(pdf),
            str(raw),
            "--registry",
            str(args.registry),
            "--key",
            key,
            "--audit",
            str(audit),
        ], check=False)
        if parser_result.returncode != 0 or not raw.exists():
            status = {
                "version": "v082-reader-build-readiness-1",
                "paper_key": key,
                "rendered": False,
                "reason": "PDF evidence parser failed strict source retention",
                "parser_returncode": parser_result.returncode,
                "audit": str(audit),
            }
            write(status_path, status)
            statuses.append(status)
            build_error = status["reason"]
            break

        ready_result = run([
            sys.executable,
            "tools/build_v082_reader_if_ready_v2.py",
            str(raw),
            str(audit),
            key,
            str(reader),
            "--task-output",
            str(task),
            "--manifest-output",
            str(manifest),
            "--report-dir",
            str(reports),
            "--status-report",
            str(status_path),
            "--schema",
            str(args.schema),
            "--shell",
            str(shell),
            "--lock",
            str(args.shell_lock),
            "--master",
            str(master),
            "--baseline",
            str(args.canonical),
            "--minimum-reader-score",
            str(args.minimum_reader_score),
            "--require-ready",
        ], check=False)
        status = load(status_path)
        statuses.append(status)
        if ready_result.returncode != 0 or not status.get("rendered"):
            build_error = status.get("reason") or "reader did not pass readiness gates"
            break

    sequential = {
        "version": "v082-sequential-reader-build-2",
        "expected_non_canvas_readers": len(ordered) - 1,
        "processed": len(statuses),
        "papers": statuses,
        "passed": len(statuses) == len(ordered) - 1 and all(item.get("rendered") for item in statuses),
        "stopped_reason": build_error,
    }
    write(reports / "SEQUENTIAL_READER_BUILD.json", sequential)
    if not sequential["passed"]:
        raise SystemExit(f"sequential build stopped: {build_error}")

    reader_files = sorted(readers.glob("*.html"))
    if len(reader_files) != len(ordered):
        raise SystemExit(f"expected {len(ordered)} readers, found {len(reader_files)}")
    run([
        sys.executable,
        "tools/browser_regression_v082.py",
        *[str(path) for path in reader_files],
        "--root",
        ".",
        "--report",
        str(reports / "BROWSER_REGRESSION.json"),
    ])

    expected_names = [paper["output"] for paper in ordered]
    actual_names = [path.name for path in reader_files]
    browser = load(reports / "BROWSER_REGRESSION.json")
    source_report = load(reports / "SOURCE_DOWNLOAD.json") if (reports / "SOURCE_DOWNLOAD.json").exists() else None
    inventory = [
        {
            "file": path.name,
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in reader_files
    ]
    errors: list[Any] = []
    if actual_names != expected_names:
        errors.append({"reader_inventory": {"expected": expected_names, "actual": actual_names}})
    if source_report is not None and not source_report.get("passed"):
        errors.append("source input audit failed")
    if not browser.get("passed") or len(browser.get("files", [])) != len(ordered):
        errors.append("browser regression failed")
    if not sequential["passed"]:
        errors.append("reader-ready manifest gate failed")

    gate = {
        "release": "V0.8.2 FINAL",
        "architecture": "immutable CANVAS product shell + paper-specific reader plans + completed bilingual manifests",
        "reader_count": len(reader_files),
        "inventory": inventory,
        "reader_build_readiness": sequential,
        "source_input_audit": source_report,
        "browser_regression": browser,
        "errors": errors,
        "passed": not errors,
    }
    write(reports / "FINAL_RELEASE_GATE.json", gate)
    write(output / "RELEASE_INDEX.json", {
        "release": "V0.8.2 FINAL",
        "passed": not errors,
        "readers": inventory,
    })
    if errors:
        raise SystemExit("final release gate failed")


if __name__ == "__main__":
    main()
