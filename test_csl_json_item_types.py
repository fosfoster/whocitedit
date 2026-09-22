#!/usr/bin/env python3
"""Offline coverage for the item type render.work_csl_json() actually emits."""
import sys

import render


# The CSL 1.0.2 item types, transcribed from the specification rather than from
# render.py: an emitted type is only useful if it is one a CSL processor
# actually accepts, so the test has to know that list independently.
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

# Representative exported work types, written out here rather than read back out
# of render.CSL_TYPES so that the expectations cannot agree with the table.
EXPECTED = {
    "article": "article-journal",
    "book": "book",
    "book-chapter": "chapter",
    "book-review": "review-book",
    "conference-paper": "paper-conference",
    "dataset": "dataset",
    "dissertation": "thesis",
    "other": "document",
    "paratext": "document",
    "preprint": "article",
    "reference-entry": "entry-encyclopedia",
    "report": "report",
    "review": "review",
    "software": "software",
}

UNKNOWN = [None, "", "journal-article", "not-a-real-type", "Article", 7]


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def main() -> int:
    bad = 0

    for work_type, expected in EXPECTED.items():
        item = render.work_csl_json({"id": "W1", "type": work_type})
        bad += check(item.get("type") == expected,
                     f"type={work_type} emitted {item.get('type')!r}, not {expected}")
        bad += check(item.get("type") == render.csl_type(work_type),
                     f"type={work_type} was not emitted through csl_type()")
        bad += check(item.get("type") in CSL_ITEM_TYPES,
                     f"type={work_type} emitted {item.get('type')!r}, not a CSL item type")

    for work_type in UNKNOWN:
        item = render.work_csl_json({"id": "W1", "type": work_type})
        bad += check("type" in item, f"unrecognised type {work_type!r} emitted no type at all")
        bad += check(item.get("type") == "document",
                     f"unrecognised type {work_type!r} did not fall back to document")

    # A work with no type key at all still has to carry one: CSL requires it.
    item = render.work_csl_json({"id": "W1"})
    bad += check(item.get("type") == "document", "a work with no type key emitted no document type")

    # The mapping change must not drop, rename, or reorder any other emitted field.
    full = {
        "id": "W4",
        "title": "A Fully Populated Work",
        "type": "book-chapter",
        "date": "2024-02-03",
        "year": 2024,
        "source": {"name": "Journal of Examples"},
        "doi": "https://doi.org/10.1000/example",
        "authors": [{"name": "First Author"}, {"name": "Second Author"}],
    }
    item = render.work_csl_json(full)
    expected_item = {
        "id": "W4",
        "title": "A Fully Populated Work",
        "type": "chapter",
        "author": [{"literal": "First Author"}, {"literal": "Second Author"}],
        "issued": {"date-parts": [[2024, 2, 3]]},
        "container-title": "Journal of Examples",
        "DOI": "10.1000/example",
    }
    bad += check(item == expected_item, f"a fully populated work emitted {item!r}")
    bad += check(list(item) == list(expected_item),
                 f"a fully populated work emitted fields in the wrong order: {list(item)!r}")

    print("test_csl_json_item_types:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
