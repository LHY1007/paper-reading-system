#!/usr/bin/env python3
from __future__ import annotations

import build_v082_reader_if_ready as base


ORIGINAL_RUN = base.run


def run(command: list[str]):
    rewritten = list(command)
    if len(rewritten) > 1:
        if rewritten[1] == "tools/validate_v082_evidence_quality.py":
            rewritten[1] = "tools/validate_v082_evidence_quality_v3.py"
        elif rewritten[1] == "tools/build_v082_reader_content_task.py":
            rewritten[1] = "tools/build_v082_reader_content_task_v3.py"
        elif rewritten[1] == "tools/audit_v082_reader_experience.py":
            rewritten[1] = "tools/audit_v082_reader_experience_v2.py"
    return ORIGINAL_RUN(rewritten)


base.run = run


if __name__ == "__main__":
    base.main()
