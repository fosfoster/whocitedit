#!/usr/bin/env python3
"""Offline coverage for the exported work type -> CSL item type mapping."""
import sys

import render


# The CSL 1.0.2 item types, transcribed from the specification rather than from
# render.py: a mapping is only useful if what it produces is a type a CSL
# processor actually accepts, so the test has to know that list independently.
CSL_ITEM_TYPES = {
    "article", "article-journal", "article-magazine", "article-newspaper",
    "bill", "book", "broadcast", "chapter", "classic", "collection", "dataset",
    "document", "entry", "entry-dictionary", "entry-encyclopedia", "event",
    "figure", "graphic", "hearing", "interview", "legal_case", "legislation",
    "manuscript", "map", "motion_picture", "musical_score", "pamphlet",
    "paper-conference", "patent", "performance", "periodical",
    "personal_communication", "post", "post-weblog", "regulation", "report",
    "review", "review-book", "software", "song", "speech", "standard", "thesis",
    "treaty", "webpage",
}

# Representative supported types, written out here rather than read back out of
# render.CSL_TYPES so that the table cannot agree with itself.
EXPECTED = {
    "article": "article-journal",
    "book": "book",
    "book-chapter": "chapter",
    "book-review": "review-book",
    "conference-paper": "paper-conference",
    "dataset": "dataset",
    "dissertation": "thesis",
    "preprint": "article",
    "report": "report",
    "review": "review",
    "software": "software",
    "other": "document",
}

UNKNOWN = ["not-a-real-type", "Article", "journal-article", "", None, 7]


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def main() -> int:
    bad = 0

    for work_type, expected in EXPECTED.items():
        bad += check(render.csl_type(work_type) == expected,
                     f"type={work_type} did not map to {expected}")

    for work_type in UNKNOWN:
        bad += check(render.csl_type(work_type) == "document",
                     f"unrecognised type {work_type!r} did not fall back to document")

    # RIS_TYPES is the exported work type vocabulary this site supports, so every
    # key of it needs a CSL type of its own -- reaching the `document` fallback
    # for a type we do know about would be a hole, not a mapping.
    supported = set(render.RIS_TYPES) | set(render.SCHEMA_TYPES)
    missing = sorted(t for t in supported if t not in render.CSL_TYPES)
    bad += check(not missing, f"supported exported types with no CSL type: {missing}")

    invalid = sorted(t for t in supported if render.csl_type(t) not in CSL_ITEM_TYPES)
    bad += check(not invalid, f"supported exported types mapped to a non-CSL type: {invalid}")

    unmapped = sorted(t for t, csl in render.CSL_TYPES.items()
                      if csl not in CSL_ITEM_TYPES)
    bad += check(not unmapped, f"CSL_TYPES holds values that are not CSL types: {unmapped}")

    bad += check("document" in CSL_ITEM_TYPES, "the fallback is not itself a valid CSL type")

    print("test_csl_json_types:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
