#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text("utf-8"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def forward_args(argv: list[str]) -> list[str]:
    """Remove wrapper-only arguments before invoking the legacy final builder."""
    forwarded: list[str] = []
    index = 0
    while index < len(argv):
        value = argv[index]
        if value == "--materialized-shell":
            index += 2
            continue
        if value.startswith("--materialized-shell="):
            index += 1
            continue
        forwarded.append(value)
        index += 1
    return forwarded


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--output-root", type=Path, default=Path("final/V0.8.2"))
    parser.add_argument("--build-root", type=Path, default=Path(".build/v082"))
    parser.add_argument("--registry", type=Path, default=Path("config/v082_paper_sources.json"))
    parser.add_argument("--shell-lock", type=Path, default=Path("config/v082_frozen_shell_lock.json"))
    parser.add_argument("--materialized-shell", type=Path, default=Path("templates/v082/V082_CANVAS_FROZEN_SHELL.html"))
    args, _ = parser.parse_known_args()

    lock = load(args.shell_lock)
    shell = args.materialized_shell
    preflight_errors: list[Any] = []
    if not shell.exists():
        preflight_errors.append(f"committed product shell is missing: {shell}")
        actual_sha = None
        actual_bytes = None
    else:
        actual_sha = sha256(shell)
        actual_bytes = shell.stat().st_size
        if actual_sha != lock.get("frozen_shell_sha256"):
            preflight_errors.append({
                "materialized_shell_sha256": {
                    "expected": lock.get("frozen_shell_sha256"),
                    "actual": actual_sha,
                }
            })
        if actual_bytes != lock.get("frozen_shell_bytes"):
            preflight_errors.append({
                "materialized_shell_bytes": {
                    "expected": lock.get("frozen_shell_bytes"),
                    "actual": actual_bytes,
                }
            })
    provenance = {
        "version": "v082-materialized-product-shell-provenance-1",
        "path": str(shell),
        "expected_sha256": lock.get("frozen_shell_sha256"),
        "actual_sha256": actual_sha,
        "expected_bytes": lock.get("frozen_shell_bytes"),
        "actual_bytes": actual_bytes,
        "lock_version": lock.get("version"),
        "errors": preflight_errors,
        "passed": not preflight_errors,
    }
    write(args.output_root / "reports" / "PRODUCT_SHELL_PROVENANCE.json", provenance)
    if preflight_errors:
        raise SystemExit("materialized product shell preflight failed")

    command = [
        sys.executable,
        "tools/run_v082_final_reader_build.py",
        *forward_args(sys.argv[1:]),
    ]
    print("+", " ".join(command), flush=True)
    result = subprocess.run(command, text=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    generated_shell = args.build_root / "templates" / "V082_CANVAS_FROZEN_SHELL.html"
    post_errors: list[Any] = []
    if not generated_shell.exists():
        post_errors.append("runtime-generated shell is missing")
    else:
        generated_sha = sha256(generated_shell)
        generated_bytes = generated_shell.stat().st_size
        if generated_sha != actual_sha or generated_bytes != actual_bytes:
            post_errors.append({
                "runtime_vs_materialized_shell": {
                    "materialized_sha256": actual_sha,
                    "runtime_sha256": generated_sha,
                    "materialized_bytes": actual_bytes,
                    "runtime_bytes": generated_bytes,
                }
            })

    registry = load(args.registry)
    papers = sorted(registry["papers"], key=lambda item: int(item["order"]))
    baseline = args.output_root / "readers" / papers[0]["output"]
    readers = [args.output_root / "readers" / item["output"] for item in papers[1:]]
    layout_report = args.output_root / "reports" / "LAYOUT_INVARIANCE.json"
    layout_command = [
        sys.executable,
        "tools/browser_layout_invariance_v082_v2.py",
        str(baseline),
        *[str(path) for path in readers],
        "--root",
        ".",
        "--report",
        str(layout_report),
    ]
    print("+", " ".join(layout_command), flush=True)
    layout_result = subprocess.run(layout_command, text=True)
    layout = load(layout_report) if layout_report.exists() else {
        "passed": False,
        "errors": ["layout invariance report was not produced"],
    }
    if layout_result.returncode != 0 or not layout.get("passed"):
        post_errors.append("browser-level fixed layout/color invariance failed")

    gate_path = args.output_root / "reports" / "FINAL_RELEASE_GATE.json"
    gate = load(gate_path)
    gate["architecture"] = "committed immutable CANVAS product shell + schema-only paper data + deterministic component renderer"
    gate["materialized_product_shell"] = provenance
    gate["runtime_shell_matches_materialized"] = not any(
        isinstance(item, dict) and "runtime_vs_materialized_shell" in item
        for item in post_errors
    )
    gate["layout_invariance"] = layout
    existing_errors = list(gate.get("errors") or [])
    existing_errors.extend(post_errors)
    gate["errors"] = existing_errors
    gate["passed"] = not existing_errors
    write(gate_path, gate)

    release_index = args.output_root / "RELEASE_INDEX.json"
    if release_index.exists():
        index = load(release_index)
        index["passed"] = gate["passed"]
        index["product_shell_sha256"] = actual_sha
        index["layout_invariance_passed"] = bool(layout.get("passed"))
        write(release_index, index)

    if post_errors:
        raise SystemExit("final product-shell and layout gate failed")


if __name__ == "__main__":
    main()
