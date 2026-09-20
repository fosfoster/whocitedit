#!/usr/bin/env python3
"""Offline coverage for the exported work type -> BibTeX entry type mapping."""
from pathlib import Path
import json
import re
import sys

import render

ROOT = Path(__file__).parent
WORKS_DIR = ROOT / "web" / "data" / "works"

# The entry types standard BibTeX defines, transcribed from its documentation
# rather than from render.py: a mapping is only useful if what it produces is an
# entry type a BibTeX processor actually accepts, so the test has to know that
# list independently.
BIBTEX_ENTRY_TYPES = {
    "article", "book", "booklet", "conference", "inbook", "incollection",
    "inproceedings", "manual", "mastersthesis", "misc", "phdthesis",
    "proceedings", "techreport", "unpublished",
}

# The whole exported work type vocabulary and the entry type each one owes,
# written out here rather than read back out of render.BIBTEX_TYPES so that the
# table cannot agree with itself.
EXPECTED = {
    "article": "article",
    "book": "book",
    "book-chapter": "incollection",
    "book-review": "article",
    "conference-abstract": "inproceedings",
    "conference-paper": "inproceedings",
    "data-paper": "article",
    "dataset": "misc",
    "dissertation": "phdthesis",
    "editorial": "article",
    "erratum": "article",
    "other": "misc",
    "paratext": "misc",
    "preprint": "misc",
    "reference-entry": "incollection",
    "report": "techreport",
    "review": "article",
    "software": "misc",
    "software-paper": "article",
}

UNKNOWN = ["not-a-real-type", "Article", "journal-article", "", None, 7]

# The work and the escaped, ordered field block test_work_bibtex.py pins for a
# complete entry. Choosing the entry type must not disturb a byte of the body.
COMPLETE = {
    "id": "W123",
    "title": "Café & # $ % _ { } ~ ^ \\ <title>",
    "year": 2024,
    "source": {"name": "Source & Proceedings"},
    "doi": "https://doi.org/10.1000/a_b",
    "authors": [{"name": "Second Author"}, {"name": "First Author"}],
}
COMPLETE_BODY = (
    "  author = {Second Author and First Author},\n"
    "  title = {Café \\& \\# \\$ \\% \\_ \\{ \\} \\textasciitilde{} "
    "\\textasciicircum{} \\textbackslash{} <title>},\n"
    "  year = {2024},\n"
    "  howpublished = {Source \\& Proceedings},\n"
    "  doi = {https://doi.org/10.1000/a\\_b}\n"
    "}\n"
)


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def entry_type(text: str) -> str:
    """The entry type a rendered BibTeX entry opens with, without its ``@``."""
    match = re.match(r"@([A-Za-z]*)\{", text)
    return match.group(1) if match else ""


def main() -> int:
    bad = 0

    # The three mappings the ticket names, read off the emitted entry itself.
    for work_type, entry in (("book", "@book"),
                             ("dissertation", "@phdthesis"),
                             ("conference-paper", "@inproceedings")):
        opening = render.work_bibtex({"id": "W1", "type": work_type}).splitlines()[0]
        bad += check(opening == f"{entry}{{W1,",
                     f"type={work_type} opened its entry with {opening!r}, expected {entry}{{W1,")

    # Every exported work type keeps the complete entry byte for byte and changes
    # only the entry type: the mapping must not touch field order or escaping.
    for work_type, entry in EXPECTED.items():
        bad += check(render.work_bibtex({**COMPLETE, "type": work_type})
                     == f"@{entry}{{W123,\n" + COMPLETE_BODY,
                     f"type={work_type} did not emit @{entry} over the original fields")

    # A typed work with nothing to print still closes its entry immediately.
    bad += check(render.work_bibtex({"id": "W-empty", "type": "book"}) == "@book{W-empty,\n}\n",
                 "a typed work with no fields lost its empty entry shape")

    for work_type in UNKNOWN:
        text = render.work_bibtex({**COMPLETE, "type": work_type})
        bad += check(entry_type(text) == "misc",
                     f"unrecognised type {work_type!r} did not fall back to misc")
        bad += check(text == "@misc{W123,\n" + COMPLETE_BODY,
                     f"the fallback for {work_type!r} did not keep the original fields")

    absent = render.work_bibtex({"id": "W123", "title": "No type at all"})
    bad += check(absent == "@misc{W123,\n  title = {No type at all}\n}\n",
                 f"a work carrying no type at all did not fall back to @misc: {absent!r}")

    # The table itself, reported rather than raised: a render.py without one at
    # all is the failure this test exists to catch, not a crash.
    table = getattr(render, "BIBTEX_TYPES", None)
    bad += check(isinstance(table, dict) and bool(table),
                 f"render.BIBTEX_TYPES is missing or empty: {table!r}")
    table = table if isinstance(table, dict) else {}

    # RIS_TYPES, SCHEMA_TYPES and CSL_TYPES are the exported work type vocabulary
    # this site supports, so every one of them needs an entry type it was given
    # on purpose -- reaching `misc` because the table forgot it is a hole.
    supported = set(render.RIS_TYPES) | set(render.SCHEMA_TYPES) | set(render.CSL_TYPES)
    missing = sorted(t for t in supported if t not in table)
    bad += check(not missing, f"supported exported types with no BibTeX entry type: {missing}")

    extra = sorted(t for t in table if t not in supported)
    bad += check(not extra, f"BIBTEX_TYPES maps types outside the exported vocabulary: {extra}")

    bad += check(sorted(EXPECTED) == sorted(supported),
                 "this test's vocabulary drifted from RIS_TYPES/SCHEMA_TYPES/CSL_TYPES: "
                 f"{sorted(set(EXPECTED) ^ supported)}")

    invalid = sorted(t for t, entry in table.items()
                     if entry not in BIBTEX_ENTRY_TYPES)
    bad += check(not invalid, f"BIBTEX_TYPES holds values that are not BibTeX entry types: {invalid}")

    bad += check("misc" in BIBTEX_ENTRY_TYPES, "the fallback is not itself a BibTeX entry type")

    # The corpus actually shipped: every work in it must open with the entry type
    # its work type owes, so a type this table never learned surfaces here.
    paths = sorted(WORKS_DIR.glob("*.json"))
    bad += check(bool(paths), "no work shards found in web/data/works")
    mismatched = []
    entries = set()
    works = 0
    for path in paths:
        for wid, w in json.loads(path.read_text(encoding="utf-8")).items():
            works += 1
            expected = EXPECTED.get(w.get("type"), "misc")
            actual = entry_type(render.work_bibtex(w))
            entries.add(actual)
            if actual != expected:
                mismatched.append(f"{wid}: type={w.get('type')!r} emitted @{actual}, expected @{expected}")
    bad += check(not mismatched,
                 f"{len(mismatched)} exported works opened the wrong entry: {mismatched[:5]}")
    print(f"exported works checked: {works}; entry types emitted: {sorted(entries)}")

    print("test_work_bibtex_types:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
