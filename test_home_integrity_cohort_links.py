#!/usr/bin/env python3
"""Offline coverage for home links into work-record integrity cohorts."""
import re
import shutil
import sys
import tempfile
from pathlib import Path

import render
from test_integrity_cohort_pages import cohort_ids, write_fixture


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def main() -> int:
    bad = 0
    temporary = Path(tempfile.mkdtemp())
    saved = render.DATA, render.SITE, render.ASSETS
    try:
        data = temporary / "data"
        works, weak_signals = write_fixture(data)
        render.DATA = data
        render.SITE = temporary / "site"
        render.ASSETS = Path(__file__).parent / "web" / "assets"
        bad += check(render.main() == 0, "synthetic render failed")

        home = (render.SITE / "index.html").read_text()
        summary = re.search(
            r'<div class="cohort-summary" aria-label="Work-record integrity summary">'
            r'(.*?)</div>',
            home,
            re.DOTALL,
        )
        bad += check(summary is not None, "home has no work-record integrity summary")
        summary_html = summary.group(1) if summary else ""
        linked_rows = re.findall(
            r'<li data-signal="([^"]+)"><span class="badge suspect">([^<]+)</span>'
            r'<a class="chart-cohort-link" href="([^"]+)"><b>([^<]+)</b></a></li>',
            summary_html,
        )

        cohorts = (
            ("title", "Missing titles", "works/missing-title/"),
            ("authors", "Missing authors", "works/missing-authors/"),
            ("doi_year", "DOI-year disagreements", "works/doi-year-disagreement/"),
            (
                "references",
                "Heavily cited records with no references",
                "works/heavily-cited-no-references/",
            ),
        )
        expected_rows = []
        for signal, label, route in cohorts:
            expected_ids = [row["id"] for row in works if signal in weak_signals[row["id"]]]
            expected_rows.append((signal, label, route, f"{len(expected_ids):,}"))

            destination = render.SITE / route / "index.html"
            bad += check(destination.exists(), f"home link destination /{route} was not generated")
            if destination.exists():
                rendered_ids = cohort_ids(destination.read_text())
                bad += check(rendered_ids == expected_ids,
                             f"/{route} does not contain the fixture's complete membership")
                bad += check(len(rendered_ids) == len(expected_ids),
                             f"home count for /{route} differs from its destination membership")

        bad += check(linked_rows == expected_rows,
                     f"home integrity links differ from the required rows: {linked_rows!r}")
        bad += check(summary_html.count('class="chart-cohort-link"') == 4,
                     "home integrity summary does not expose exactly four linked counts")
        bad += check('<ul class="cohort-bands chart-legend">' in summary_html,
                     "home integrity links do not reuse cohort and link styling")
    finally:
        render.DATA, render.SITE, render.ASSETS = saved
        shutil.rmtree(temporary, ignore_errors=True)

    print("test_home_integrity_cohort_links:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
