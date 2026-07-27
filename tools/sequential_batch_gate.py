#!/usr/bin/env python3
"""Run paper-reader generation strictly one paper at a time.

The next paper is never started until the current output passes both the
primary validator and the independent interaction-contract validator.
"""
from __future__ import annotations
import argparse, json, subprocess
from pathlib import Path


def run(command: list[str], label: str) -> None:
    completed = subprocess.run(command, text=True)
    if completed.returncode:
        raise SystemExit(f"{label} failed with exit code {completed.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path, help="JSON list of source/output pairs in required order")
    parser.add_argument("--generate", required=True, help="Generator command; receives source and output paths")
    parser.add_argument("--validate", required=True, help="Primary validator command; receives output path")
    parser.add_argument("--secondary", required=True, help="Independent interaction validator; receives output path")
    args = parser.parse_args()
    items = json.loads(args.manifest.read_text("utf-8"))
    if not isinstance(items, list) or not items:
        raise SystemExit("manifest must be a non-empty ordered list")
    results = []
    for index, item in enumerate(items):
        source = Path(item["source"])
        output = Path(item["output"])
        print(f"[{index + 1}/{len(items)}] generate {source.name}", flush=True)
        run([*args.generate.split(), str(source), str(output)], "generation")
        run([*args.validate.split(), str(output)], "primary validation")
        run([*args.secondary.split(), str(output)], "secondary interaction validation")
        results.append({"index": index, "source": str(source), "output": str(output), "passed": True})
        print(f"[{index + 1}/{len(items)}] PASS", flush=True)
    print(json.dumps({"passed": True, "total": len(results), "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
