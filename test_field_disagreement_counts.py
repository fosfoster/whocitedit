#!/usr/bin/env python3
"""render.field_disagreement_counts() counts a field's own source-disagreement members.

render_field only ever sees works-index rows, which carry no quality evidence or
source_comparison, so it cannot compute cohort membership itself. main() already
builds a corpus-wide `source_disagreement_members` map (cohort key -> {work id:
observations}); this helper intersects that global map with one field's own
works so the /fields/<key>/ panel can report counts scoped to that field, never
a corpus-wide total.
"""
import inspect
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

import render
from test_field_pages import write_fixture

REAL_FIELD = render.render_field


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def works_with_ids(*ids):
    return [{"id": wid} for wid in ids]


def main() -> int:
    bad = 0
    cohorts = list(render.SOURCE_DISAGREEMENT_COHORTS)
    bad += check(len(cohorts) >= 2, "SOURCE_DISAGREEMENT_COHORTS needs at least two entries to test")
    title_crossref, title_europepmc = cohorts[0], cohorts[1]

    # A work that's a cohort member but isn't in this field must not be counted,
    # and a work in this field that's a member of two cohorts (a `both_disagree`
    # verdict) must count in both.
    members = {
        title_crossref: {"W-in-field": ["obs"], "W-other-field": ["obs"]},
        title_europepmc: {"W-in-field": ["obs"]},
    }
    field_works = works_with_ids("W-in-field", "W-solo")
    counts = render.field_disagreement_counts(field_works, members)

    bad += check(len(counts) == len(cohorts),
                 f"expected one entry per cohort ({len(cohorts)}), got {len(counts)}")
    bad += check([entry["key"] for entry in counts] == cohorts,
                 "entries are not in SOURCE_DISAGREEMENT_COHORTS iteration order")

    by_key = {entry["key"]: entry for entry in counts}
    bad += check(by_key[title_crossref]["count"] == 1,
                 f"W-other-field leaked into this field's count: {by_key[title_crossref]}")
    bad += check(by_key[title_crossref]["config"] == render.SOURCE_DISAGREEMENT_COHORTS[title_crossref],
                 "entry config does not match SOURCE_DISAGREEMENT_COHORTS' config for its key")
    bad += check(by_key[title_europepmc]["count"] == 1,
                 f"W-in-field's second cohort membership was not counted: {by_key[title_europepmc]}")

    # Zero-count cohorts (none of this field's cohorts here have members) must
    # still be present, not dropped.
    for key in cohorts[2:]:
        bad += check(by_key[key]["count"] == 0,
                     f"cohort {key} should be zero-count but got {by_key[key]}")
        bad += check(key in by_key, f"zero-count cohort {key} missing from result")

    # None and an empty mapping must behave as all-zero counts.
    for empty in (None, {}):
        zeroed = render.field_disagreement_counts(field_works, empty)
        bad += check(len(zeroed) == len(cohorts),
                     f"members={empty!r}: expected {len(cohorts)} entries, got {len(zeroed)}")
        bad += check(all(entry["count"] == 0 for entry in zeroed),
                     f"members={empty!r}: expected all-zero counts, got {zeroed}")
        bad += check([entry["key"] for entry in zeroed] == cohorts,
                     f"members={empty!r}: entries are not in cohort order")

    # main() passes the membership mapping it already computes into render_field
    # as a keyword, over the test_field_pages corpus fixture.
    tmp = Path(tempfile.mkdtemp())
    saved = (render.DATA, render.SITE, render.ASSETS, getattr(render, "NAV_FIELDS", []))
    try:
        render.ASSETS = Path(__file__).parent / "web" / "assets"
        data = tmp / "data"
        fields, works, _ = write_fixture(data)
        render.DATA = data
        render.SITE = tmp / "site"

        with mock.patch.object(render, "render_field", wraps=render.render_field) as pages:
            result = render.main()

        bad += check(result == 0, f"render.main() returned {result}")
        bad += check(pages.call_count == len(fields),
                     f"render_field was called {pages.call_count} times, not once per field")

        expected_members = {cohort: {} for cohort in cohorts}
        for call in pages.call_args_list:
            arguments = inspect.signature(REAL_FIELD).bind(*call.args, **call.kwargs)
            arguments.apply_defaults()
            bound = arguments.arguments
            bad += check("disagreement_members" in bound,
                         "render_field was not given a disagreement_members argument")
            bad += check(bound.get("disagreement_members") == expected_members,
                         "main() did not pass its computed source_disagreement_members map "
                         f"into render_field: got {bound.get('disagreement_members')!r}")

        # Positional callers with only (field, works, corpus) -- the existing
        # test_listing_itemlist.py call shape -- must keep working.
        page = render.render_field(fields[0], works, {"definition": {}})
        bad += check(isinstance(page, str) and "<html" in page.lower(),
                     "render_field with only three positional arguments no longer works")
    finally:
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_field_disagreement_counts:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
