#!/usr/bin/env python3
"""Committed-corpus coverage: every exported work's @type resolves via SCHEMA_TYPES."""
from collections import Counter
from pathlib import Path
import json
import re
import sys

import render

ROOT = Path(__file__).parent
WORKS_DIR = ROOT / "web" / "data" / "works"

# Spelled out rather than derived from render.SCHEMA_TYPES so a typo or a
# non-schema.org value added to that mapping fails here instead of passing.
KNOWN_SCHEMA_TYPES = {
    "ScholarlyArticle",
    "Dataset",
    "Book",
    "Chapter",
    "Thesis",
    "Report",
    "SoftwareSourceCode",
    "CreativeWork",
}


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def schema_type(page):
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
    return json.loads(match.group(1)) if match else None


def main() -> int:
    bad = 0
    type_counts = Counter()
    unmapped_types = set()

    for work_type, schema_type_name in sorted(render.SCHEMA_TYPES.items()):
        bad += check(schema_type_name in KNOWN_SCHEMA_TYPES,
                     f"SCHEMA_TYPES[{work_type!r}] = {schema_type_name!r} is not a known schema.org type")

    paths = sorted(WORKS_DIR.glob("*.json"))
    bad += check(bool(paths), "no work shards found in web/data/works")

    for path in paths:
        shard = json.loads(path.read_text(encoding="utf-8"))
        for wid, w in shard.items():
            page = render.work_head_metadata(w, render.canonical_url(f"w/{wid}/"))
            ld = schema_type(page)
            bad += check(ld is not None, f"{wid}: no JSON-LD block emitted")
            if ld is None:
                continue

            expected = render.SCHEMA_TYPES.get(w.get("type"), "ScholarlyArticle")
            actual = ld.get("@type")
            bad += check(actual == expected,
                         f"{wid}: type={w.get('type')!r} rendered @type={actual!r}, expected {expected!r}")
            bad += check(actual in KNOWN_SCHEMA_TYPES,
                         f"{wid}: rendered @type={actual!r} is outside the closed SCHEMA_TYPES set")

            type_counts[w.get("type")] += 1
            if w.get("type") not in render.SCHEMA_TYPES:
                unmapped_types.add(w.get("type"))

    print("work type distribution:")
    for work_type, count in sorted(type_counts.items(), key=lambda item: (-item[1], str(item[0]))):
        print(f"  {work_type!r}: {count}")

    print("exported types defaulting to ScholarlyArticle (not in SCHEMA_TYPES):",
          sorted(t for t in unmapped_types if t is not None) or "none")

    print("test_work_schema_type_corpus:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
