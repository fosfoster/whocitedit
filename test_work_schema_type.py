#!/usr/bin/env python3
"""Offline coverage for the OpenAlex work type -> schema.org @type mapping."""
import json
import re
import sys

import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def work(**changes):
    value = {
        "id": "W123",
        "title": "Complete work",
        "year": 2024,
        "date": "2024-02-03",
        "doi": "https://doi.org/10.1000/complete",
        "source": {"id": "S456", "name": "Source publication"},
        "oa": {"url": "https://example.test/open.pdf", "license": None},
        "abstract": {"text": "", "reason": "rendered"},
        "cited_by_count": 4,
        "in_corpus_cited_by": 1,
        "authors": [{"id": "A1", "name": "First Author"}],
        "topics": [],
        "graph": {"nodes": [], "shown": 0, "available": 0},
        "quality": {"band": "complete", "sentence": "Complete", "evidence": []},
        "raw": None,
        "openalex_url": "https://openalex.org/W123",
    }
    value.update(changes)
    return value


def schema_type(page):
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
    return json.loads(match.group(1)) if match else None


def render_work(value):
    return render.render_work(value, {}, {}, {}, {}, set())


def main() -> int:
    bad = 0

    ld = schema_type(render_work(work()))
    bad += check(ld is not None and ld.get("@type") == "ScholarlyArticle",
                 "work with no type did not default to ScholarlyArticle")

    ld = schema_type(render_work(work(type="article")))
    bad += check(ld is not None and ld.get("@type") == "ScholarlyArticle",
                 "type=article did not map to ScholarlyArticle")

    ld = schema_type(render_work(work(type="dataset")))
    bad += check(ld is not None and ld.get("@type") == "Dataset",
                 "type=dataset did not map to Dataset")

    ld = schema_type(render_work(work(type="preprint")))
    bad += check(ld is not None and ld.get("@type") == "ScholarlyArticle",
                 "type=preprint did not map to ScholarlyArticle")

    ld = schema_type(render_work(work(type="book-chapter")))
    bad += check(ld is not None and ld.get("@type") == "Chapter",
                 "type=book-chapter did not map to Chapter")

    ld = schema_type(render_work(work(type="not-a-real-type")))
    bad += check(ld is not None and ld.get("@type") == "ScholarlyArticle",
                 "unknown type did not default to ScholarlyArticle")
    bad += check(ld.get("isPartOf", {}).get("@type") == "CreativeWork",
                 "nested isPartOf @type is no longer CreativeWork")

    bad += check(bool(render.SCHEMA_TYPES) and
                 all(isinstance(v, str) and v for v in render.SCHEMA_TYPES.values()),
                 "SCHEMA_TYPES contains a non-string or empty value")

    print("test_work_schema_type:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
