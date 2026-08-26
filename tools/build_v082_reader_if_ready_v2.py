#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import build_v082_reader_if_ready as base


ORIGINAL_RUN = base.run
ORIGINAL_COPY2 = base.shutil.copy2


def semantic_report_path(command: list[str]) -> Path:
    try:
        report = Path(command[command.index("--report") + 1])
    except (ValueError, IndexError):
        report = Path("final/V0.8.2/reports/READER_CONTENT.json")
    return report.with_name(report.stem.replace("_READER_CONTENT", "_SEMANTIC_GROUNDING") + report.suffix)


def strong_review_report_path(command: list[str]) -> Path:
    try:
        report = Path(command[command.index("--report") + 1])
    except (ValueError, IndexError):
        report = Path("final/V0.8.2/reports/READER_CONTENT.json")
    return report.with_name(report.stem.replace("_READER_CONTENT", "_STRONG_AI_REVIEW") + report.suffix)


def v083_contract_report_path(command: list[str]) -> Path:
    try:
        report = Path(command[command.index("--report") + 1])
    except (ValueError, IndexError):
        report = Path("final/V0.8.2/reports/CONTENT.json")
    return report.with_name(report.stem.replace("_CONTENT", "_V083_CONTRACT") + report.suffix)


def manifest_plan_path(destination: Path) -> Path | None:
    try:
        manifest = json.loads(destination.read_text("utf-8"))
        key = str((manifest.get("paper") or {}).get("key") or "").strip()
    except Exception:
        return None
    candidate = Path("config/v082_reader_content_plans") / f"{key}.json"
    return candidate if key and candidate.exists() else None


def run_visible(command: list[str]) -> None:
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if completed.returncode != 0:
        raise RuntimeError(f"V0.8.3 manifest finalization failed: {' '.join(command)}")


def copy2_and_normalize(source, destination, *args, **kwargs):
    result = ORIGINAL_COPY2(source, destination, *args, **kwargs)
    destination = Path(destination)
    run_visible([
        sys.executable,
        "tools/normalize_v082_paper_tables.py",
        str(destination),
    ])
    finalize = [
        sys.executable,
        "tools/finalize_v083_manifest.py",
        str(destination),
    ]
    if len(sys.argv) >= 2:
        finalize += ["--evidence", sys.argv[1]]
    plan = manifest_plan_path(destination)
    if plan:
        finalize += ["--plan", str(plan)]
    run_visible(finalize)
    return result


def run(command: list[str]):
    rewritten = list(command)
    if len(rewritten) > 1:
        if rewritten[1] == "tools/validate_v082_evidence_quality.py":
            rewritten[1] = "tools/validate_v082_evidence_quality_v5.py"
        elif rewritten[1] == "tools/build_v082_reader_content_task.py":
            rewritten[1] = "tools/build_v082_reader_content_task_v4.py"
        elif rewritten[1] == "tools/audit_v082_reader_experience.py":
            rewritten[1] = "tools/audit_v082_reader_experience_v2.py"
        elif rewritten[1] == "tools/validate_v082_reader_content_quality.py":
            if len(sys.argv) < 2:
                return {
                    "command": rewritten,
                    "returncode": 98,
                    "stdout_tail": "",
                    "stderr_tail": "raw evidence path is unavailable for semantic validation",
                }
            manifest = Path(rewritten[2])
            try:
                paper_key = str((json.loads(manifest.read_text("utf-8")).get("paper") or {}).get("key"))
            except Exception:
                paper_key = ""
            review_path = Path("content/v082_reviews") / f"{paper_key}.json"
            strong_command = [
                sys.executable,
                "tools/validate_v082_strong_ai_review.py",
                str(manifest),
                "--review",
                str(review_path),
                "--report",
                str(strong_review_report_path(rewritten)),
            ]
            strong = ORIGINAL_RUN(strong_command)
            if strong["returncode"] != 0:
                return strong
            semantic_command = [
                sys.executable,
                "tools/validate_v082_reader_semantics_v4.py",
                str(manifest),
                "--evidence",
                sys.argv[1],
                "--report",
                str(semantic_report_path(rewritten)),
            ]
            semantic = ORIGINAL_RUN(semantic_command)
            if semantic["returncode"] != 0:
                return semantic
        elif rewritten[1] == "tools/validate_v082_final_manifest.py":
            manifest = rewritten[2]
            contract_command = [
                sys.executable,
                "tools/validate_v083_manifest_contract.py",
                manifest,
                "--report",
                str(v083_contract_report_path(rewritten)),
            ]
            contract = ORIGINAL_RUN(contract_command)
            if contract["returncode"] != 0:
                return contract
    return ORIGINAL_RUN(rewritten)


base.run = run
base.shutil.copy2 = copy2_and_normalize


if __name__ == "__main__":
    base.main()
