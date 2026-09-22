#!/usr/bin/env python3
"""Offline coverage for csl_type()/CSL_TYPES, and a guard that this ticket's
work left the RIS and BibTeX renderers untouched.

This ticket only defines the CSL type mapping; it does not wire it into any
renderer. RIS_TYPES/render_ris and the BibTeX renderer already export their
own vocabulary independently, so a change here has no business touching them
-- these hashes are a tripwire for exactly that.
"""
import hashlib
import inspect
import sys

import render

# CSL 1.0.2's item types, transcribed from the specification rather than read
# back out of render.py: a mapping is only useful if what it produces is a
# type a CSL processor actually accepts.
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

# Hashes of the untouched RIS/BibTeX renderers, captured before this ticket's
# work began. A mismatch means something outside this ticket's scope changed.
UNTOUCHED_HASHES = {
    "RIS_TYPES": "ccf40b77edf4240675fa038d4f2b912710e7868b134ac2f3edf946088151f3b0",
    "render_ris": "3bca97f6afc285c77c5153d267945ee26623c015b50a9e182a5b4a2281772d3b",
    "bibtex_type": "33f0065b34824d31112644f6f2736a63a00964933d5886e6f5380f0f7ab53786",
    "work_bibtex": "329e02b4b249413a467fabf9a920a06210dd3f7d9dd2514fda1f1e062840fb54",
}


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def source_hash(name):
    obj = getattr(render, name)
    text = inspect.getsource(obj) if callable(obj) else repr(obj)
    return hashlib.sha256(text.encode()).hexdigest()


def main() -> int:
    bad = 0

    bad += check(render.csl_type("book-chapter") == "chapter",
                 "csl_type('book-chapter') did not map to 'chapter'")
    bad += check(render.csl_type(None) == "document",
                 "csl_type(None) did not fall back to 'document'")

    invalid = sorted(t for t, csl in render.CSL_TYPES.items() if csl not in CSL_ITEM_TYPES)
    bad += check(not invalid, f"CSL_TYPES holds values that are not CSL 1.0.2 types: {invalid}")

    for name, expected in UNTOUCHED_HASHES.items():
        bad += check(source_hash(name) == expected,
                     f"render.{name} changed byte-for-byte since this ticket's baseline")

    print("test_csl_type_mapping:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
