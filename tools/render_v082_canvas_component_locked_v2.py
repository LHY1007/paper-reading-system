#!/usr/bin/env python3
from __future__ import annotations

import re

import render_v082_canvas_component_locked_v2_core as core


def replace_const_expression(script: str, name: str, expression: str) -> str:
    match = re.search(rf"\b(?:const|let|var)\s+{re.escape(name)}\s*=", script)
    if not match:
        raise ValueError(f"missing JavaScript assignment for {name}")
    pos = match.end()
    quote = None
    escaped = False
    depth = 0
    index = pos
    while index < len(script):
        char = script[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        else:
            if char in "'\"`":
                quote = char
            elif char in "([{":
                depth += 1
            elif char in ")]}":
                depth -= 1
            elif char == ";" and depth == 0:
                return script[:pos] + expression + script[index:]
        index += 1
    raise ValueError(f"unterminated JavaScript assignment for {name}")


core.base.replace_const_expression = replace_const_expression


if __name__ == "__main__":
    core.main()
