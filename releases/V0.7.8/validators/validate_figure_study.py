#!/usr/bin/env python3
import json
import sys
from pathlib import Path


def balanced(text, start):
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
    raise ValueError("V6_STUDY object is incomplete")


def main(path):
    text = Path(path).read_text("utf-8")
    marker = "const V6_STUDY="
    position = text.find(marker)
    if position < 0:
        raise SystemExit("V6_STUDY missing")

    data = json.loads(balanced(text, position + len(marker)))
    errors = []
    expected = {
        "figure-1": 10,
        "figure-2": 10,
        "figure-3": 14,
        "figure-4": 10,
        "figure-5": 15,
    }

    for figure_id, expected_count in expected.items():
        figure = data.get(figure_id)
        panels = (figure or {}).get("panels", [])
        if len(panels) != expected_count:
            errors.append(
                f"{figure_id}: expected {expected_count} panels, found {len(panels)}"
            )
        for panel_index, panel in enumerate(panels):
            body = panel[1].strip() if len(panel) > 1 else ""
            if len(body) < 180:
                errors.append(
                    f"{figure_id} panel {panel_index + 1}: only {len(body)} characters"
                )
            if "与正文" in body and "相呼应" in body:
                errors.append(
                    f"{figure_id} panel {panel_index + 1}: forbidden shortcut wording"
                )

    if "window.v078EnhanceStudyTerms" not in text:
        errors.append("dedicated figure-study term enhancer missing")
    if "#v6StudyDoc .term-pop" not in text:
        errors.append("figure-study term style missing")

    if errors:
        print("\n".join(errors))
        return 1

    print("figure-study contract passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
