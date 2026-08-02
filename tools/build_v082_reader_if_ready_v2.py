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


def copy2_and_normalize(source, destination, *args, **kwargs):
    result = ORIGINAL_COPY2(source, destination, *args, **kwargs)
    command = [
        sys.executable,
        "tools/normalize_v082_paper_tables.py",
        str(destination),
    ]
    completed = subprocess.run(command, text=True, capture_output=True)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if completed.returncode != 0:
        raise RuntimeError(f"paper-specific structured table normalization failed for {destination}")
    return result


def run(command: list[str]):
    rewritten = list(command)
    if len(rewritten) > 1:
        if rewritten[1] == "tools/validate_v082_evidence_quality.py":
            rewritten[1] = "tools/validate_v082_evidence_quality_v5.py"
        elif rewritten[1] == "tools/build_v082_reader_content_task.py":
            rewritten[1] = "tools/build_v082_reader_content_task_v3.py"
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
    return ORIGINAL_RUN(rewritten)


base.run = run
base.shutil.copy2 = copy2_and_normalize


if __name__ == "__main__":
    base.main()
