#!/usr/bin/env python3
"""Every rendered disagreement cell carries the href `href_from_cohorts` returns.

The six cells are checked one cohort key at a time against the helper's own
output, so a cell that keeps a hand-written path -- or any path the helper did
not produce -- fails on its own line rather than inside a single roll-up.
"""
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import render
from test_methodology_source_matrix import write_fixture


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def disagreement_cells(html):
    """Map (source label, field label) to the href of that row's last cell."""
    panel = re.search(
        r'<h2>Source record field comparisons</h2>.*?<tbody>(.*?)</tbody>', html, re.S,
    )
    if panel is None:
        return {}
    rows = re.findall(
        r'<tr><td>(.*?)</td><td>(.*?)</td><td class="num">.*?</td>'
        r'<td class="num">.*?</td><td class="num">(.*?)</td></tr>',
        panel.group(1),
    )
    cells = {}
    for source_label, field_label, cell in rows:
        href = re.search(r'<a href="([^"]*)"', cell)
        cells[(source_label, field_label)] = href.group(1) if href else None
    return cells


def target_of(site, href):
    """Resolve a rendered href the way `test_full_corpus_render` resolves one."""
    requested = href if href.startswith("/") else f"/methodology/{href}"
    return Path(os.path.normpath(site / requested.lstrip("/"))) / "index.html"


def main() -> int:
    bad = 0
    temporary = Path(tempfile.mkdtemp())
    saved = render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS
    try:
        data = temporary / "data"
        write_fixture(data)
        render.DATA = data
        render.SITE = temporary / "site"
        render.ASSETS = Path(__file__).parent / "web" / "assets"
        bad += check(render.main() == 0, "synthetic render failed")

        page = render.SITE / "methodology" / "index.html"
        html = page.read_text() if page.exists() else ""
        cells = disagreement_cells(html)
        bad += check(len(render.SOURCE_DISAGREEMENT_COHORTS) == 6,
                     "there are no longer six source-disagreement cohorts")
        bad += check(len(cells) == 6,
                     f"methodology renders {len(cells)} disagreement cell(s), expected 6")

        # Looked up once rather than called directly, so a build without the
        # helper reports every cell it fails to cover instead of raising here.
        helper = getattr(render, "href_from_cohorts", None)
        bad += check(callable(helper), "render has no href_from_cohorts helper")

        for cohort_key, config in render.SOURCE_DISAGREEMENT_COHORTS.items():
            label = (config["source_label"], config["field_label"])
            expected = helper(cohort_key) if callable(helper) else "<no helper>"
            actual = cells.get(label)
            bad += check(
                actual == expected,
                f"the {label[0]} {label[1].lower()} disagreement cell links to {actual!r}, "
                f"but href_from_cohorts({cohort_key!r}) returns {expected!r}",
            )
            target = target_of(render.SITE, expected) if actual == expected else None
            bad += check(
                target is not None and target.is_file(),
                f"the {label[0]} {label[1].lower()} disagreement cell href {actual!r} "
                "does not reach a rendered cohort page",
            )
    finally:
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(temporary, ignore_errors=True)

    print("test_render_disagreement_hrefs:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
