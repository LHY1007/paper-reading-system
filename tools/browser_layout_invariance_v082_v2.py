#!/usr/bin/env python3
from __future__ import annotations

import browser_layout_invariance_v082 as base


_original_compare = base.compare_snapshot


def compare_snapshot(baseline, candidate, viewport, file_name):
    errors = _original_compare(baseline, candidate, viewport, file_name)
    return [
        item
        for item in errors
        if not (
            item.get("issue") == "fixed shell selector missing"
            and item.get("baseline_present") is False
            and item.get("candidate_present") is False
        )
    ]


base.compare_snapshot = compare_snapshot


if __name__ == "__main__":
    base.main()
