#!/usr/bin/env python3
"""Every disagreement cell on the methodology page links to the cohort page named
by SOURCE_DISAGREEMENT_COHORTS, not by a second mapping or a hardcoded string."""
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
    """Map (source label, field label) to the raw disagreement cell of that row."""
    panel = re.search(
        r'<h2>Source record field comparisons</h2>.*?<tbody>(.*?)</tbody>', html, re.S,
    )
    if panel is None:
        return None
    return {
        (source, field): cell
        for source, field, cell in re.findall(
            r'<tr><td>(.*?)</td><td>(.*?)</td><td class="num">.*?</td>'
            r'<td class="num">.*?</td><td class="num">(.*?)</td></tr>',
            panel.group(1),
        )
    }


def main():
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
        bad += check(cells is not None, "methodology has no source-field comparison table")
        cells = cells or {}
        bad += check(len(cells) == 6, f"methodology renders {len(cells)} source-field rows, expected six")

        for (field, source), config in render.SOURCE_DISAGREEMENT_COHORTS.items():
            row = (config["source_label"], config["field_label"])
            cell = cells.get(row)
            bad += check(cell is not None, f"methodology has no {source} {field} row")
            if cell is None:
                continue
            link = re.fullmatch(r'<a href="([^"]*)">([\d,]+)</a>', cell)
            bad += check(link is not None,
                         f"the {source} {field} disagreement cell carries no href: {cell!r}")
            if link is None:
                continue
            expected = f'../{config["path"]}'
            bad += check(link.group(1) == expected,
                         f"the {source} {field} disagreement cell links to {link.group(1)!r}, "
                         f"but SOURCE_DISAGREEMENT_COHORTS names {expected!r}")
            destination = page.parent / expected / "index.html"
            bad += check(destination.is_file(),
                         f"the {source} {field} disagreement cell links to {expected!r}, "
                         "which is not generated")
    finally:
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(temporary, ignore_errors=True)

    print("test_href_from_cohorts:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
