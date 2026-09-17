#!/usr/bin/env python3
"""Coverage for derive.europepmc_work_fields()."""
import json
import sys
from pathlib import Path

import derive

ROOT = Path(__file__).parent
SEARCH_FIXTURE = json.loads(
    (ROOT / "docs" / "fixtures" / "europepmc" / "search.json").read_text()
)


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def main() -> int:
    bad = 0

    # The committed core-shaped fixture yields its journalInfo fields.
    core_result = SEARCH_FIXTURE["resultList"]["result"][0]
    fields = derive.europepmc_work_fields(core_result)
    bad += check(fields["doi"] == "10.5555/source-paper",
                 "core fixture DOI was not passed through")
    bad += check(fields["title"] == "A fixture Europe PMC source paper",
                 "core fixture title was not passed through")
    bad += check(fields["venue"] == "Journal of Fixtures",
                 "core fixture venue did not come from journalInfo.journal.title")
    bad += check(fields["venue_short"] == "J Fixtures",
                 "core fixture venue_short did not come from journalInfo.journal.medlineAbbreviation")
    bad += check(fields["publication_date"] == "2024-01-15",
                 "core fixture publication_date did not prefer firstPublicationDate")

    # A lite-shaped result carrying only journalTitle/pubYear.
    lite_result = {
        "doi": "10.5555/lite-paper",
        "title": "A lite-shaped result",
        "journalTitle": "Lite Journal",
        "pubYear": "2021",
    }
    lite_fields = derive.europepmc_work_fields(lite_result)
    bad += check(lite_fields["venue"] == "Lite Journal",
                 "lite result did not fall back to journalTitle")
    bad += check(lite_fields["venue_short"] is None,
                 "lite result manufactured a venue_short that was never present")
    bad += check(lite_fields["publication_date"] == "2021",
                 "lite result did not fall back to a bare YYYY pubYear")

    # journalInfo missing entirely.
    missing_result = {"doi": "10.5555/missing", "title": "No journal info"}
    missing_fields = derive.europepmc_work_fields(missing_result)
    bad += check(
        missing_fields["venue"] is None and missing_fields["venue_short"] is None
        and missing_fields["publication_date"] is None,
        "a result with no journalInfo did not return all-None venue/date fields",
    )

    # journalInfo present but as a string, not a dict.
    string_result = {"doi": "10.5555/weird", "title": "Weird shape", "journalInfo": "not a dict"}
    string_fields = derive.europepmc_work_fields(string_result)
    bad += check(
        string_fields["venue"] is None and string_fields["venue_short"] is None,
        "a non-dict journalInfo raised or leaked into the venue fields instead of returning None",
    )

    # An empty/whitespace title yields None, never a placeholder.
    for bad_title in ("", "   "):
        blank_fields = derive.europepmc_work_fields({"title": bad_title})
        bad += check(blank_fields["title"] is None,
                     f"a title of {bad_title!r} did not yield None")

    print("test_europepmc_fields:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
