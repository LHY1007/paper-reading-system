#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(command), flush=True)
    result = subprocess.run(command, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="", flush=True)
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr, flush=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}")
    return result


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text("utf-8"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")


def commit_outputs(paths: list[Path], key: str, branch: str) -> dict[str, Any]:
    run(["git", "config", "user.name", "github-actions[bot]"])
    run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"])
    run(["git", "add", *[str(path) for path in paths]])
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return {"changed": False, "reason": "validated manifest and review already current"}
    run(["git", "commit", "-m", f"Regenerate and independently review V0.8.2 reader content for {key}"])
    for attempt in range(1, 5):
        run(["git", "fetch", "origin", branch])
        rebase = run(["git", "rebase", f"origin/{branch}"], check=False)
        if rebase.returncode != 0:
            run(["git", "rebase", "--abort"], check=False)
            time.sleep(5 * attempt)
            continue
        push = run(["git", "push", "origin", f"HEAD:{branch}"], check=False)
        if push.returncode == 0:
            return {"changed": True, "pushed": True, "attempt": attempt}
        time.sleep(8 * attempt)
    raise RuntimeError("validated content could not be pushed after four attempts")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and independently review one V0.8.2 paper, then commit only a complete passed result")
    parser.add_argument("paper_key")
    parser.add_argument("--registry", type=Path, default=Path("config/v082_paper_sources.json"))
    parser.add_argument("--pdf-dir", type=Path, default=Path(".build/v082/pdfs"))
    parser.add_argument("--plans-dir", type=Path, default=Path("config/v082_reader_content_plans"))
    parser.add_argument("--manifest-dir", type=Path, default=Path("content/v082_manifests"))
    parser.add_argument("--review-dir", type=Path, default=Path("content/v082_reviews"))
    parser.add_argument("--work-root", type=Path, default=Path(".build/v082/strong-one"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".build/v082/model-cache"))
    parser.add_argument("--branch", default="v0.8x-batch-diagnosis")
    parser.add_argument("--generator", default="tools/generate_v082_reader_manifest_with_strong_ai_v13.py")
    args = parser.parse_args()

    if not (os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_MODELS_TOKEN")):
        raise SystemExit("GitHub Models token is required")

    registry = load(args.registry)
    paper = next((item for item in registry.get("papers") or [] if str(item.get("key")) == args.paper_key), None)
    if not paper:
        raise SystemExit(f"paper key not registered: {args.paper_key}")
    order = int(paper["order"])
    pdf = args.pdf_dir / f"{order:02d}_{args.paper_key}.pdf"
    plan = args.plans_dir / f"{args.paper_key}.json"
    if not pdf.exists():
        raise SystemExit(f"exact source PDF is missing: {pdf}")
    if not plan.exists():
        raise SystemExit(f"paper-specific plan is missing: {plan}")

    work = args.work_root / args.paper_key
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    evidence = work / "evidence.json"
    audit = work / "evidence-audit.json"
    generated = work / "manifest.json"
    review = generated.with_suffix(".strong-ai-review.json")
    reports = work / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    status_path = reports / "COMPONENT_BUILD_STATUS.json"
    status: dict[str, Any] = {
        "version": "v082-one-paper-strong-ai-build-1",
        "paper_key": args.paper_key,
        "order": order,
        "source_pdf": str(pdf),
        "generator": args.generator,
        "steps": {},
        "passed": False,
    }

    commands: list[tuple[str, list[str]]] = [
        ("evidence", [
            sys.executable, "tools/build_pdf_native_manifest_v082.py",
            str(pdf), str(evidence), "--registry", str(args.registry),
            "--key", args.paper_key, "--audit", str(audit),
        ]),
        ("evidence_quality", [
            sys.executable, "tools/validate_v082_evidence_quality_v5.py",
            str(evidence), "--audit", str(audit),
            "--report", str(reports / "EVIDENCE_QUALITY.json"),
        ]),
        ("strong_ai_generation", [
            sys.executable, args.generator,
            str(evidence), str(plan), str(generated),
            "--cache-dir", str(args.cache_dir),
        ]),
        ("strong_ai_review_gate", [
            sys.executable, "tools/validate_v082_strong_ai_review.py",
            str(generated), "--review", str(review),
            "--report", str(reports / "STRONG_AI_REVIEW_GATE.json"),
        ]),
        ("semantic_grounding", [
            sys.executable, "tools/validate_v082_reader_semantics_v4.py",
            str(generated), "--evidence", str(evidence),
            "--report", str(reports / "SEMANTIC_GROUNDING.json"),
        ]),
        ("reader_content", [
            sys.executable, "tools/validate_v082_reader_content_quality.py",
            str(generated), "--report", str(reports / "READER_CONTENT.json"),
        ]),
        ("final_manifest", [
            sys.executable, "tools/validate_v082_final_manifest.py",
            str(generated), "--schema", "schemas/paper_content_manifest_v082.schema.json",
            "--audit", str(audit), "--report", str(reports / "FINAL_MANIFEST.json"),
        ]),
        ("code_boundary", [
            sys.executable, "tools/validate_v082_manifest_code_boundary.py",
            str(generated), "--report", str(reports / "CODE_BOUNDARY.json"),
        ]),
    ]

    try:
        for name, command in commands:
            result = run(command, check=False)
            status["steps"][name] = {"returncode": result.returncode}
            write(status_path, status)
            if result.returncode != 0:
                raise RuntimeError(f"{name} failed")

        args.manifest_dir.mkdir(parents=True, exist_ok=True)
        args.review_dir.mkdir(parents=True, exist_ok=True)
        curated = args.manifest_dir / f"{args.paper_key}.json"
        curated_review = args.review_dir / f"{args.paper_key}.json"
        shutil.copy2(generated, curated)
        shutil.copy2(review, curated_review)
        status["commit"] = commit_outputs([curated, curated_review], args.paper_key, args.branch)
        status["passed"] = True
        status["reason"] = "every variable component was generated one at a time, independently reviewed, grounded, validated and committed"
        write(status_path, status)
    except Exception as exc:
        generated.unlink(missing_ok=True)
        review.unlink(missing_ok=True)
        status["reason"] = f"{type(exc).__name__}: {exc}"
        status["traceback"] = traceback.format_exc()[-8000:]
        write(status_path, status)
        raise


if __name__ == "__main__":
    main()
