#!/usr/bin/env python3
"""work_csl_json() always emits a 'type' field via csl_type()."""
import sys

import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def main() -> int:
    failures = 0

    item = render.work_csl_json({"id": "W1", "type": "book-chapter"})
    failures += check(
        item["type"] == "chapter",
        f"expected type 'chapter' for book-chapter, got {item['type']!r}",
    )

    item = render.work_csl_json({"id": "W1"})
    failures += check(
        item["type"] == "document",
        f"expected type 'document' for a missing work type, got {item['type']!r}",
    )

    if failures:
        print(f"{failures} failure(s)")
    else:
        print("OK")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
