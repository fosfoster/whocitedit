#!/usr/bin/env python3
"""Offline coverage for the CSL-JSON author, date, container-title and DOI fields."""
import sys

import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def main() -> int:
    bad = 0

    full_date = {
        "id": "W1",
        "title": "A Full Date Work",
        "type": "article",
        "date": "2024-02-03",
        "year": 2024,
        "source": {"name": "Journal of Examples"},
        "doi": "https://doi.org/10.1000/example",
        "authors": [{"name": "First Author"}, {"name": "Second Author"}],
    }
    item = render.work_csl_json(full_date)
    bad += check(item["issued"] == {"date-parts": [[2024, 2, 3]]},
                 "a full date did not derive full CSL date-parts")
    bad += check(item["author"] == [{"literal": "First Author"}, {"literal": "Second Author"}],
                 "authors were not rendered as literal names")
    bad += check(item["container-title"] == "Journal of Examples",
                 "container-title was not derived from the source name")
    bad += check(item["DOI"] == "10.1000/example",
                 "a doi.org URL was not reduced to a bare DOI")
    bad += check(item["type"] == "article-journal",
                 "type was not mapped through the CSL vocabulary")

    year_only = {
        "id": "W2",
        "title": "A Year-Only Work",
        "type": "book",
        "date": None,
        "year": 1843,
        "source": {"name": "Analytical Engine Press"},
        "doi": None,
        "authors": [{"name": "Ada Lovelace"}],
    }
    item = render.work_csl_json(year_only)
    bad += check(item["issued"] == {"date-parts": [[1843]]},
                 "a missing full date did not fall back to the bare year")

    sparse = {
        "id": "W3",
        "title": None,
        "type": None,
        "date": None,
        "year": None,
        "source": {},
        "doi": None,
        "authors": [],
    }
    item = render.work_csl_json(sparse)
    bad += check(item["type"] == "document",
                 "an absent type did not fall back to the CSL document type")
    bad += check("author" not in item, "an absent author list was not omitted")
    bad += check("issued" not in item, "an absent date and year did not omit issued")
    bad += check("container-title" not in item, "an absent source name was not omitted")
    bad += check("DOI" not in item, "an absent doi was not omitted")
    bad += check(item == {"id": "W3", "type": "document"},
                 "a fully sparse work emitted unexpected fields")

    print("test_csl_json_fields:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
