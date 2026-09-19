#!/usr/bin/env python3
"""N-source title/date/venue agreement helpers.

A third (or fourth) source only becomes usable once the two-source
comparisons in derive.py can fold in an arbitrary number of per-source
assertions. These cases exercise the N-ary rule directly: fewer than two
comparable assertions is `unavailable`, all of them matching is `agree`,
any mismatch is `disagree` -- without ever going through a database or a
network call.
"""
import sys

import derive


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def main() -> int:
    bad = 0

    # -- title -------------------------------------------------------------

    bad += check(
        derive.title_comparison_status_n(["Deep Learning & Cats", "Deep Learning & Cats.", "DEEP LEARNING & CATS"])
        == "agree",
        "three titles differing only by case/punctuation must agree",
    )
    bad += check(
        derive.title_comparison_status_n(["Deep Learning & Cats", "Deep Learning & Cats", "A Different Title"])
        == "disagree",
        "one dissenting title among three must disagree",
    )
    bad += check(
        derive.title_comparison_status_n(["Only One Title"]) == "unavailable",
        "a single asserting source must be unavailable, not agree",
    )
    bad += check(
        derive.title_comparison_status_n([]) == "unavailable",
        "no sources at all must be unavailable",
    )
    bad += check(
        derive.title_comparison_status_n([f"{derive.NO_TITLE_PREFIX} — no title]", "Some Title"]) == "unavailable",
        "the OpenAlex no-title placeholder must never be compared as an assertion",
    )
    bad += check(
        derive.title_comparison_status_n(
            [f"{derive.NO_TITLE_PREFIX} — no title]", "Some Title", "Some Title"]
        )
        == "agree",
        "the placeholder must be ignored entirely, leaving the other two to agree",
    )
    bad += check(
        derive.title_comparison_status_n(["Some Title", None, ""]) == "unavailable",
        "a source asserting nothing (None or empty) must not count toward comparison",
    )

    # -- date ----------------------------------------------------------------

    bad += check(
        derive.date_comparison_n(["2021-07-04", "2021-07-04", "2021-07-04"]) == ("agree", "day"),
        "three matching full dates must agree at day precision",
    )
    bad += check(
        derive.date_comparison_n(["2021-07-04", "2021-07-04", "2021-08-04"]) == ("disagree", "day"),
        "one dissenting full date among three must disagree",
    )
    bad += check(
        derive.date_comparison_n(["2021", "2021-07-04", "2021-07-15"]) == ("agree", "year"),
        "a year-only source against two full dates must agree at year precision, never expanded",
    )
    bad += check(
        derive.date_comparison_n(["2021", "2022-07-04"]) == ("disagree", "year"),
        "a year-only source disagreeing with a full date must disagree at year precision",
    )
    bad += check(
        derive.date_comparison_n(["2021-07-04", None, ""]) == ("unavailable", None),
        "a source asserting no date must be ignored rather than counted",
    )
    bad += check(
        derive.date_comparison_n(["2021-07-04"]) == ("unavailable", None),
        "only one source asserting a date must be unavailable",
    )

    # -- venue -----------------------------------------------------------------

    bad += check(
        derive.venue_comparison_status_n(
            [("Journal of Testing", None), ("Journal of Testing", "J. Test."), ("The Journal of Testing", None)]
        )
        == "agree",
        "three sources naming the same venue (with an article and case differences) must agree",
    )
    bad += check(
        derive.venue_comparison_status_n(
            [("Journal of Testing", None), ("A Completely Different Venue", None)]
        )
        == "disagree",
        "two sources naming different venues must disagree",
    )
    bad += check(
        derive.venue_comparison_status_n(
            [("Journal of Testing", None), ("Journal of Testing (JoT)", "Journal of Testing")]
        )
        == "agree",
        "a venue matching another source's abbreviation only must still agree",
    )
    bad += check(
        derive.venue_comparison_status_n([("Journal of Testing", None)]) == "unavailable",
        "only one source asserting a venue must be unavailable",
    )
    bad += check(
        derive.venue_comparison_status_n(
            [("Journal of Testing", None), (None, None), ("", None)]
        )
        == "unavailable",
        "sources asserting nothing must be ignored, leaving only one real assertion",
    )

    # -- the two-argument wrappers must keep their exact pre-existing behaviour --

    bad += check(
        derive.title_comparison_status("Deep Learning & Cats.", "DEEP LEARNING & CATS") == "agree",
        "title_comparison_status must still agree through normalize_title folding",
    )
    bad += check(
        derive.title_comparison_status(f"{derive.NO_TITLE_PREFIX} — no title]", "Some Title") == "unavailable",
        "title_comparison_status must still treat the OpenAlex placeholder as unavailable, not disagree",
    )
    bad += check(
        derive.title_comparison_status("Some Title", f"{derive.NO_TITLE_PREFIX} — no title]") == "disagree",
        "only the OpenAlex side carries our placeholder: a Crossref title starting with the same "
        "text stays a comparable assertion and must still disagree",
    )
    bad += check(
        derive.title_comparison_status(None, "Some Title") == "unavailable"
        and derive.title_comparison_status("Some Title", None) == "unavailable",
        "title_comparison_status must still be unavailable when either side asserts nothing",
    )
    bad += check(
        derive.date_comparison("2021-07-04", "2021") == ("agree", "year"),
        "date_comparison must still compare only as deep as the shallower source",
    )
    bad += check(
        derive.venue_comparison_status("Journal of Testing", "A Completely Different Venue", "Journal of Testing")
        == "agree",
        "venue_comparison_status must still agree against the short form alone",
    )
    bad += check(
        derive.venue_comparison_status(None, "Journal of Testing", None) == "unavailable",
        "venue_comparison_status must still be unavailable without an OpenAlex venue",
    )

    print("test_source_agreement:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
