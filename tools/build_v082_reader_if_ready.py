#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def run(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(command, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    }


def write_status(path: Path, status: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(status, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a V0.8.2 paper only when its paper-specific task and completed reader manifest pass every content gate"
    )
    parser.add_argument("raw_manifest", type=Path)
    parser.add_argument("audit", type=Path)
    parser.add_argument("paper_key")
    parser.add_argument("output_reader", type=Path)
    parser.add_argument("--task-output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--status-report", type=Path, required=True)
    parser.add_argument("--curated-dir", type=Path, default=Path("content/v082_manifests"))
    parser.add_argument("--plans-dir", type=Path, default=Path("config/v082_reader_content_plans"))
    parser.add_argument("--blueprint", type=Path, default=Path("config/v082_reader_content_blueprint.json"))
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--shell", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--minimum-reader-score", type=float, default=30.0)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()

    args.report_dir.mkdir(parents=True, exist_ok=True)
    args.task_output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
    args.output_reader.parent.mkdir(parents=True, exist_ok=True)

    prefix = args.paper_key.replace("/", "-")
    status: dict[str, Any] = {
        "version": "v082-reader-build-readiness-1",
        "paper_key": args.paper_key,
        "raw_manifest": str(args.raw_manifest),
        "audit": str(args.audit),
        "task": str(args.task_output),
        "curated_manifest": str(args.curated_dir / f"{args.paper_key}.json"),
        "output_reader": str(args.output_reader),
        "ready_for_rendering": False,
        "rendered": False,
        "reason": None,
        "steps": {},
    }

    task_command = [
        sys.executable,
        "tools/build_v082_reader_content_task.py",
        str(args.raw_manifest),
        str(args.task_output),
        "--paper-key",
        args.paper_key,
        "--plans-dir",
        str(args.plans_dir),
        "--blueprint",
        str(args.blueprint),
    ]
    status["steps"]["task"] = run(task_command)
    if status["steps"]["task"]["returncode"] != 0 or not args.task_output.exists():
        status["reason"] = "reader content task could not be created"
        write_status(args.status_report, status)
        if args.require_ready:
            raise SystemExit(1)
        return

    task = json.loads(args.task_output.read_text("utf-8"))
    status["task_version"] = task.get("task_version")
    status["paper_specific_plan"] = task.get("paper_specific_plan_path")
    status["plan_errors"] = task.get("plan_errors")
    status["ready_for_content_generation"] = task.get("ready_for_content_generation")
    if not task.get("ready_for_content_generation"):
        status["reason"] = "paper-specific reader content plan is missing or invalid"
        write_status(args.status_report, status)
        if args.require_ready:
            raise SystemExit(1)
        return

    curated = args.curated_dir / f"{args.paper_key}.json"
    if not curated.exists():
        status["reason"] = "completed reader-ready manifest is missing; raw evidence and machine translation must not be rendered"
        write_status(args.status_report, status)
        if args.require_ready:
            raise SystemExit(1)
        return

    shutil.copy2(curated, args.manifest_output)
    status["manifest_output"] = str(args.manifest_output)

    reports = {
        "reader_content": args.report_dir / f"{prefix}_READER_CONTENT.json",
        "content": args.report_dir / f"{prefix}_CONTENT.json",
        "boundary": args.report_dir / f"{prefix}_MANIFEST_CODE_BOUNDARY.json",
        "render": args.report_dir / f"{prefix}_RENDER.json",
        "shell": args.report_dir / f"{prefix}_SHELL.json",
        "components": args.report_dir / f"{prefix}_COMPONENTS.json",
        "architecture": args.report_dir / f"{prefix}_ARCHITECTURE.json",
        "reader_experience": args.report_dir / f"{prefix}_READER_EXPERIENCE.json",
        "reader_experience_md": args.report_dir / f"{prefix}_READER_EXPERIENCE.md",
    }
    status["reports"] = {key: str(path) for key, path in reports.items()}

    validation_commands = {
        "reader_content": [
            sys.executable,
            "tools/validate_v082_reader_content_quality.py",
            str(args.manifest_output),
            "--report",
            str(reports["reader_content"]),
        ],
        "content": [
            sys.executable,
            "tools/validate_v082_final_manifest.py",
            str(args.manifest_output),
            "--schema",
            str(args.schema),
            "--audit",
            str(args.audit),
            "--report",
            str(reports["content"]),
        ],
        "boundary": [
            sys.executable,
            "tools/validate_v082_manifest_code_boundary.py",
            str(args.manifest_output),
            "--report",
            str(reports["boundary"]),
        ],
    }
    for name, command in validation_commands.items():
        status["steps"][name] = run(command)

    failed_content_steps = [
        name for name in validation_commands if status["steps"][name]["returncode"] != 0
    ]
    if failed_content_steps:
        status["reason"] = "completed manifest failed reader/content gates"
        status["failed_steps"] = failed_content_steps
        write_status(args.status_report, status)
        if args.require_ready:
            raise SystemExit(1)
        return

    status["ready_for_rendering"] = True
    render_commands = {
        "render": [
            sys.executable,
            "tools/render_v082_from_frozen_shell.py",
            str(args.manifest_output),
            str(args.output_reader),
            "--shell",
            str(args.shell),
            "--lock",
            str(args.lock),
            "--schema",
            str(args.schema),
            "--report",
            str(reports["render"]),
        ],
        "shell": [
            sys.executable,
            "tools/validate_v082_canvas_shell_lock.py",
            str(args.output_reader),
            "--canonical",
            str(args.master),
            "--report",
            str(reports["shell"]),
        ],
        "components": [
            sys.executable,
            "tools/validate_v082_canvas_components.py",
            str(args.output_reader),
            "--report",
            str(reports["components"]),
        ],
        "architecture": [
            sys.executable,
            "tools/validate_v082_rendered_architecture.py",
            str(args.output_reader),
            "--shell",
            str(args.shell),
            "--manifest",
            str(args.manifest_output),
            "--lock",
            str(args.lock),
            "--report",
            str(reports["architecture"]),
        ],
        "reader_experience": [
            sys.executable,
            "tools/audit_v082_reader_experience.py",
            str(args.baseline),
            str(args.output_reader),
            "--json",
            str(reports["reader_experience"]),
            "--md",
            str(reports["reader_experience_md"]),
            "--minimum-score",
            str(args.minimum_reader_score),
        ],
    }

    for name, command in render_commands.items():
        if name != "render" and not args.output_reader.exists():
            status["steps"][name] = {"returncode": 99, "skipped": True, "reason": "reader not rendered"}
            continue
        status["steps"][name] = run(command)
        if status["steps"][name]["returncode"] != 0:
            break

    failed_render_steps = [
        name
        for name in render_commands
        if status["steps"].get(name, {}).get("returncode") not in (0, None)
    ]
    if failed_render_steps:
        status["reason"] = "rendered reader failed product or reader-experience gates"
        status["failed_steps"] = failed_render_steps
        if args.output_reader.exists():
            args.output_reader.unlink()
        write_status(args.status_report, status)
        if args.require_ready:
            raise SystemExit(1)
        return

    status["rendered"] = True
    status["reason"] = "reader-ready manifest passed all pre-render and post-render gates"
    write_status(args.status_report, status)


if __name__ == "__main__":
    main()
