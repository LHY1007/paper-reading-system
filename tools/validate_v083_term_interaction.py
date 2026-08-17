#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_SNIPPETS = [
    'id="canvas-v083-term-interaction-script"',
    "const V='0.8.3'",
    "document.addEventListener('click'",
    "document.addEventListener('keydown'",
    "stopImmediatePropagation()",
    "closest('.term-pop')",
    "#termTooltip",
    "window.__CANVAS_V083_CONTRACT__",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('html', type=Path)
    ap.add_argument('--report', type=Path)
    args = ap.parse_args()
    text = args.html.read_text('utf-8')
    errors = [f'missing:{s}' for s in REQUIRED_SNIPPETS if s not in text]
    # The formal standard must retain all important V0.8.2 reader contracts.
    for selector in ['sentence-piece', 'figure-study-button', 'referencePop', 'showTerms', 'termTooltip']:
        if selector not in text:
            errors.append(f'legacy-reader-contract-missing:{selector}')
    result = {
        'version': '0.8.3',
        'html': str(args.html),
        'term_nodes': text.count('class="term-pop"'),
        'passed': not errors,
        'errors': errors,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
