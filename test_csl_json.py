#!/usr/bin/env python3
"""Offline coverage for render_csl_json() wiring work_csl_json() end-to-end."""
import json
import sys

import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def main() -> int:
    bad = 0

    work = {
        "id": "W1",
        "title": "A Fully Populated Work",
        "type": "article",
        "date": "2024-02-03",
        "year": 2024,
        "source": {"name": "Journal of Examples"},
        "doi": "https://doi.org/10.1000/example",
        "authors": [{"name": "First Author"}, {"name": "Second Author"}],
    }

    rendered = render.render_csl_json(work)
    item = json.loads(rendered)

    bad += check(item == render.work_csl_json(work),
                 "render_csl_json does not serialize render.work_csl_json's own output")

    # The acceptance surface for this ticket: id, title, type, author, issued
    # date-parts, container-title and DOI, all reached through work_csl_json()
    # rather than a second, parallel derivation in render_csl_json() itself.
    bad += check(item["id"] == "W1", "id was not passed through")
    bad += check(item["title"] == "A Fully Populated Work", "title was not passed through")
    bad += check(item["type"] == "article-journal",
                 "type was not mapped through the CSL type-mapping helper")
    bad += check(item["author"] == [{"literal": "First Author"}, {"literal": "Second Author"}],
                 "authors were not rendered as CSL literal names")
    bad += check(item["issued"] == {"date-parts": [[2024, 2, 3]]},
                 "issued date-parts were not derived from the full date")
    bad += check(item["container-title"] == "Journal of Examples",
                 "container-title was not derived from the source name")
    bad += check(item["DOI"] == "10.1000/example",
                 "DOI was not reduced to a bare DOI")

    # render_csl_json() must not carry its own, parallel date/DOI derivation --
    # tkt_fc1d910f5e0d's cancelled attempt at this ticket did exactly that, with
    # its own bare_doi/csl_date_parts helpers duplicating #57's _csl_issued and
    # _csl_doi. Guard against that regression by holding the module's helpers,
    # not just their output, to a single implementation each.
    year_only_doi = render._csl_doi("10.1000/bare")
    bad += check(year_only_doi == "10.1000/bare", "_csl_doi is not reused by work_csl_json")
    issued_only = render._csl_issued({"date": None, "year": 1999})
    bad += check(issued_only == {"date-parts": [[1999]]}, "_csl_issued is not reused by work_csl_json")

    no_doi_work = {**work, "doi": None}
    no_doi_item = json.loads(render.render_csl_json(no_doi_work))
    bad += check("DOI" not in no_doi_item, "a work without a DOI emitted a DOI field")

    print("test_csl_json:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
