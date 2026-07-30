#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import traceback
from typing import Any


def run(command: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command), flush=True)
    result = subprocess.run(command, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}")
    return result


def load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text("utf-8"))


def write(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")


def git_commit_manifest(path: pathlib.Path, key: str, branch: str) -> dict[str, Any]:
    run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
    run(["git", "add", str(path)], check=True)
    diff = run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        return {"changed": False, "committed": False, "pushed": False, "reason": "manifest already current"}
    run(["git", "commit", "-m", f"Add validated V0.8.2 reader manifest for {key}"], check=True)
    for attempt in range(1, 4):
        fetch = run(["git", "fetch", "origin", branch])
        if fetch.returncode != 0:
            time.sleep(3 * attempt)
            continue
        rebase = run(["git", "rebase", f"origin/{branch}"])
        if rebase.returncode != 0:
            run(["git", "rebase", "--abort"])
            raise RuntimeError(f"cannot rebase validated {key} manifest onto latest branch")
        push = run(["git", "push", "origin", f"HEAD:{branch}"])
        if push.returncode == 0:
            return {"changed": True, "committed": True, "pushed": True, "attempt": attempt}
        time.sleep(4 * attempt)
    raise RuntimeError(f"validated {key} manifest could not be pushed after three attempts")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate, validate and commit V0.8.2 manifests strictly one paper at a time")
    parser.add_argument("--registry", type=pathlib.Path, default=pathlib.Path("config/v082_paper_sources.json"))
    parser.add_argument("--pdf-dir", type=pathlib.Path, default=pathlib.Path(".build/v082/pdfs"))
    parser.add_argument("--evidence-dir", type=pathlib.Path, default=pathlib.Path(".build/v082/batch-evidence"))
    parser.add_argument("--audit-dir", type=pathlib.Path, default=pathlib.Path(".build/v082/batch-audits"))
    parser.add_argument("--report-dir", type=pathlib.Path, default=pathlib.Path(".build/v082/batch-reports"))
    parser.add_argument("--generated-dir", type=pathlib.Path, default=pathlib.Path(".build/v082/generated-manifests"))
    parser.add_argument("--manifest-dir", type=pathlib.Path, default=pathlib.Path("content/v082_manifests"))
    parser.add_argument("--plans-dir", type=pathlib.Path, default=pathlib.Path("config/v082_reader_content_plans"))
    parser.add_argument("--cache-dir", type=pathlib.Path, default=pathlib.Path(".build/v082/model-cache"))
    parser.add_argument("--branch", default="v0.8x-batch-diagnosis")
    parser.add_argument("--generator", default="tools/generate_v082_reader_manifest_with_github_models_v3.py")
    args = parser.parse_args()

    if not (os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_MODELS_TOKEN")):
        raise SystemExit("GitHub Models token is required")

    for directory in (
        args.evidence_dir,
        args.audit_dir,
        args.report_dir,
        args.generated_dir,
        args.manifest_dir,
        args.cache_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    registry = load(args.registry)
    papers = [item for item in sorted(registry["papers"], key=lambda value: int(value["order"])) if int(item["order"]) != 0]
    statuses: list[dict[str, Any]] = []
    summary_path = args.report_dir / "SEQUENTIAL_MANIFEST_GENERATION.json"

    for paper in papers:
        key = str(paper["key"])
        order = int(paper["order"])
        pdf = args.pdf_dir / f"{order:02d}_{key}.pdf"
        evidence = args.evidence_dir / f"{key}.json"
        audit = args.audit_dir / f"{key}.json"
        generated = args.generated_dir / f"{key}.json"
        curated = args.manifest_dir / f"{key}.json"
        plan = args.plans_dir / f"{key}.json"
        paper_reports = args.report_dir / key
        paper_reports.mkdir(parents=True, exist_ok=True)
        generated.unlink(missing_ok=True)
        status: dict[str, Any] = {
            "order": order,
            "key": key,
            "pdf": str(pdf),
            "pdf_available": pdf.exists(),
            "plan_available": plan.exists(),
            "generated_manifest": str(generated),
            "curated_manifest": str(curated),
            "passed": False,
            "committed": False,
            "steps": {},
        }
        statuses.append(status)
        print(f"\n===== STRICT SEQUENTIAL MANIFEST {order:02d} {key} =====", flush=True)

        if not pdf.exists():
            status["reason"] = "exact source PDF unavailable"
            write(summary_path, {"papers": statuses})
            continue
        if not plan.exists():
            status["reason"] = "paper-specific content plan unavailable"
            write(summary_path, {"papers": statuses})
            continue

        try:
            commands: list[tuple[str, list[str]]] = [
                (
                    "evidence",
                    [
                        sys.executable,
                        "tools/build_pdf_native_manifest_v082.py",
                        str(pdf),
                        str(evidence),
                        "--registry",
                        str(args.registry),
                        "--key",
                        key,
                        "--audit",
                        str(audit),
                    ],
                ),
                (
                    "evidence_quality",
                    [
                        sys.executable,
                        "tools/validate_v082_evidence_quality_v5.py",
                        str(evidence),
                        "--audit",
                        str(audit),
                        "--report",
                        str(paper_reports / "EVIDENCE_QUALITY.json"),
                    ],
                ),
                (
                    "generation",
                    [
                        sys.executable,
                        args.generator,
                        str(evidence),
                        str(plan),
                        str(generated),
                        "--cache-dir",
                        str(args.cache_dir),
                    ],
                ),
                (
                    "semantic_grounding",
                    [
                        sys.executable,
                        "tools/validate_v082_reader_semantics_v3.py",
                        str(generated),
                        "--evidence",
                        str(evidence),
                        "--report",
                        str(paper_reports / "SEMANTIC_GROUNDING.json"),
                    ],
                ),
                (
                    "reader_content",
                    [
                        sys.executable,
                        "tools/validate_v082_reader_content_quality.py",
                        str(generated),
                        "--report",
                        str(paper_reports / "READER_CONTENT.json"),
                    ],
                ),
                (
                    "final_manifest",
                    [
                        sys.executable,
                        "tools/validate_v082_final_manifest.py",
                        str(generated),
                        "--schema",
                        "schemas/paper_content_manifest_v082.schema.json",
                        "--audit",
                        str(audit),
                        "--report",
                        str(paper_reports / "FINAL_MANIFEST.json"),
                    ],
                ),
                (
                    "code_boundary",
                    [
                        sys.executable,
                        "tools/validate_v082_manifest_code_boundary.py",
                        str(generated),
                        "--report",
                        str(paper_reports / "CODE_BOUNDARY.json"),
                    ],
                ),
            ]
            for name, command in commands:
                result = run(command)
                status["steps"][name] = {"returncode": result.returncode}
                if result.returncode != 0:
                    raise RuntimeError(f"{name} failed")

            shutil.copy2(generated, curated)
            commit = git_commit_manifest(curated, key, args.branch)
            status["commit"] = commit
            status["committed"] = bool(commit.get("committed") or not commit.get("changed"))
            status["passed"] = True
            status["reason"] = "source evidence, grounded content, schema and code boundary passed; manifest persisted"
        except Exception as exc:
            generated.unlink(missing_ok=True)
            status["reason"] = f"{type(exc).__name__}: {exc}"
            status["traceback"] = traceback.format_exc()[-6000:]

        write(summary_path, {"papers": statuses})

    failed = [item["key"] for item in statuses if not item.get("passed")]
    summary = {
        "version": "v082-strict-sequential-manifest-generation-2",
        "expected_non_canvas": len(papers),
        "passed_count": sum(bool(item.get("passed")) for item in statuses),
        "failed_keys": failed,
        "all_expected_passed": not failed and len(statuses) == len(papers),
        "papers": statuses,
    }
    write(summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit("one or more papers failed strict sequential manifest generation: " + ", ".join(failed))


if __name__ == "__main__":
    main()
