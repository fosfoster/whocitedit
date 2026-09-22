#!/usr/bin/env python3
"""Direct coverage for the href_from_cohorts helper, one test per cohort key."""
import sys

import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def main() -> int:
    bad = 0

    bad += check(
        render.href_from_cohorts(("title", "crossref")) == "/works/title-disagreement/crossref/",
        "title/crossref href did not match the expected path",
    )
    bad += check(
        render.href_from_cohorts(("title", "europepmc")) == "/works/title-disagreement/europepmc/",
        "title/europepmc href did not match the expected path",
    )
    bad += check(
        render.href_from_cohorts(("venue", "crossref")) == "/works/venue-disagreement/crossref/",
        "venue/crossref href did not match the expected path",
    )
    bad += check(
        render.href_from_cohorts(("venue", "europepmc")) == "/works/venue-disagreement/europepmc/",
        "venue/europepmc href did not match the expected path",
    )
    bad += check(
        render.href_from_cohorts(("date", "crossref")) == "/works/date-disagreement/crossref/",
        "date/crossref href did not match the expected path",
    )
    bad += check(
        render.href_from_cohorts(("date", "europepmc")) == "/works/date-disagreement/europepmc/",
        "date/europepmc href did not match the expected path",
    )

    if bad:
        print(f"FAIL: {bad} check(s) failed")
        return 1
    print("OK: href_from_cohorts covers every SOURCE_DISAGREEMENT_COHORTS key")
    return 0


if __name__ == "__main__":
    sys.exit(main())
