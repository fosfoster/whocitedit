#!/usr/bin/env python3
"""Offline coverage for home-page links into uncertainty cohorts."""
import re
import shutil
import sys
import tempfile
from pathlib import Path

import render
from test_cohort_pages import write_fixture


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (render.DATA, render.SITE, render.ASSETS)
    try:
        data = tmp / "data"
        authors, works = write_fixture(data)
        render.DATA = data
        render.SITE = tmp / "site"
        render.ASSETS = Path(__file__).parent / "web" / "assets"
        bad += check(render.main() == 0, "synthetic render failed")

        home = (render.SITE / "index.html").read_text()
        cohorts = (
            ("low", len([row for row in authors if row["band"] == "low"]),
             "authors/low-confidence/"),
            ("partial", len([row for row in works if row["quality"] == "partial"]),
             "works/partial/"),
            ("suspect", len([row for row in works if row["quality"] == "suspect"]),
             "works/suspect/"),
        )
        for label, count, route in cohorts:
            count_text = f"{count:,}"
            pattern = (rf'<span><i class="legend-[^"]+"></i>{label} '
                       rf'<a class="chart-cohort-link" href="{route}"><b>{count_text}</b></a>')
            bad += check(re.search(pattern, home) is not None,
                         f"home {label} count does not link to /{route}")
            bad += check((render.SITE / route / "index.html").exists(),
                         f"home {label} link destination is not generated")

        for label, count in (("high", 1), ("medium", 1), ("complete", 2)):
            pattern = rf'{label} <a class="chart-cohort-link"[^>]*><b>{count}</b></a>'
            bad += check(re.search(pattern, home) is None,
                         f"home {label} count incorrectly implies a cohort link")

        css = (render.ASSETS / "style.css").read_text()
        bad += check(".chart-legend .chart-cohort-link:hover" in css,
                     "cohort count links lack a hover styling hook")
        bad += check(".chart-legend .chart-cohort-link:focus-visible" in css,
                     "cohort count links lack a keyboard-focus styling hook")
    finally:
        render.DATA, render.SITE, render.ASSETS = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_home_cohort_links:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
