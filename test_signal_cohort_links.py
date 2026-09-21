#!/usr/bin/env python3
"""Offline coverage for links from blended cohorts to their named signals."""
import re
import shutil
import sys
import tempfile
from pathlib import Path

import render
from test_signal_cohort_pages import write_fixture


COHORTS = (
    ("missing-authors", "whether the record lists any authors at all"),
    ("no-references", "whether it records references behind a large citation count"),
    ("doi-year-mismatch", "whether the year embedded in its DOI agrees with its own publication year"),
    ("missing-title", "whether it has a title"),
)


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def hrefs(html):
    return re.findall(r'<a href="([^"]+)"', html)


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (render.DATA, render.SITE, render.ASSETS)
    try:
        data = tmp / "data"
        write_fixture(data)
        render.DATA = data
        render.SITE = tmp / "site"
        render.ASSETS = Path(__file__).parent / "web" / "assets"
        bad += check(render.main() == 0, "synthetic render failed")

        pages = (
            ("methodology/index.html", "../works/"),
            ("works/partial/index.html", "../"),
            ("works/suspect/index.html", "../"),
        )
        for route, prefix in pages:
            page = render.SITE / route
            bad += check(page.exists(), f"missing /{route[:-len('index.html')]}")
            if not page.exists():
                continue
            html = re.sub(r"\s+", " ", page.read_text())
            links = hrefs(html)
            for cohort, check_text in COHORTS:
                href = f"{prefix}{cohort}/"
                bad += check(href in links, f"/{route[:-len('index.html')]} does not link to /works/{cohort}/")
                if route == "methodology/index.html":
                    bad += check(f'<a href="{href}">{check_text}</a>' in html,
                                 f"/methodology/ does not link the {cohort} check text")
                destination = page.parent / href / "index.html"
                bad += check(destination.is_file(),
                             f"/{route[:-len('index.html')]} link to /works/{cohort}/ is not generated")
    finally:
        render.DATA, render.SITE, render.ASSETS = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_signal_cohort_links:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
