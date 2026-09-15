#!/usr/bin/env python3
"""Keep interactive graph labels from being clipped at the SVG boundary."""
import re
import sys
from pathlib import Path


STYLE = Path(__file__).parent / "web" / "assets" / "style.css"


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def declaration_block(css, selector):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    match = re.search(rf"(?m)^\s*{re.escape(selector)}\s*\{{([^}}]*)\}}", css)
    return match.group(1) if match else None


def main() -> int:
    css = STYLE.read_text()
    block = declaration_block(css, ".fg svg")
    bad = check(block is not None, ".fg svg declaration block is missing")

    if block is not None:
        overflows = re.findall(r"(?:^|;)\s*overflow\s*:\s*([^;}]*)", block, re.I)
        bad += check(
            bool(overflows) and overflows[-1].strip().lower() == "visible",
            ".fg svg must end with overflow: visible so edge labels remain readable",
        )

    print("test_graph_labels:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
