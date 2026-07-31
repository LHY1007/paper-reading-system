#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import generate_v082_reader_manifest_with_google_translate_v11 as v11


def normalized_evidence(source: Path) -> Path:
    data = json.loads(source.read_text("utf-8"))
    changed = False
    for section in data.get("sections") or []:
        level = int(section.get("level") or 2)
        normalized = min(4, max(2, level))
        if normalized != level:
            section["level"] = normalized
            changed = True
    if not changed:
        return source
    handle = tempfile.NamedTemporaryFile(prefix="v082-evidence-", suffix=".json", delete=False)
    target = Path(handle.name)
    handle.close()
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return target


if __name__ == "__main__":
    if len(sys.argv) < 4:
        raise SystemExit("usage: generator evidence plan output [options]")
    sys.argv[1] = str(normalized_evidence(Path(sys.argv[1])))
    sys.argv[0] = Path(__file__).name
    v11.v8.v7.main()
