#!/usr/bin/env python3
"""Every disagreement cell on the methodology page carries the href the
cohort-to-href helper computes from that row's SOURCE_DISAGREEMENT_COHORTS
entry -- not a second mapping, and not a string written out beside it."""
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


def cell_href(cell):
    """The href a disagreement cell carries, or None when it carries no link."""
    link = re.fullmatch(r'<a href="([^"]*)">[\d,]+</a>', cell or "")
    return link.group(1) if link else None


def render_cells(site):
    """Render the synthetic corpus into `site`; return its methodology page and cells."""
    render.SITE = site
    rendered = render.main()
    page = site / "methodology" / "index.html"
    html = page.read_text() if page.exists() else ""
    return rendered, page, disagreement_cells(html)


def main():
    bad = 0
    temporary = Path(tempfile.mkdtemp())
    saved = render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS
    cohorts = dict(render.SOURCE_DISAGREEMENT_COHORTS)
    helper = getattr(render, "href_for_disagreement_cohort", None)
    try:
        data = temporary / "data"
        write_fixture(data)
        render.DATA = data
        render.ASSETS = Path(__file__).parent / "web" / "assets"

        bad += check(callable(helper),
                     "render exposes no cohort-to-href helper to compute these cells with")
        rendered, page, cells = render_cells(temporary / "site")
        bad += check(rendered == 0, "synthetic render failed")
        bad += check(cells is not None, "methodology has no source-field comparison table")
        cells = cells or {}
        bad += check(len(cells) == len(cohorts),
                     f"methodology renders {len(cells)} source-field rows, expected {len(cohorts)}")

        for (field, source), config in cohorts.items():
            cell = cells.get((config["source_label"], config["field_label"]))
            bad += check(cell is not None, f"methodology has no {source} {field} row")
            if cell is None:
                continue
            href = cell_href(cell)
            bad += check(href is not None,
                         f"the {source} {field} disagreement cell carries no href: {cell!r}")
            if href is None:
                continue
            entry = f'../{config["path"]}'
            bad += check(href == entry,
                         f"the {source} {field} disagreement cell links to {href!r}, "
                         f"but SOURCE_DISAGREEMENT_COHORTS names {entry!r}")
            if callable(helper):
                bad += check(helper(field, source) == href,
                             f"the {source} {field} disagreement cell links to {href!r}, "
                             f"but the helper computes {helper(field, source)!r}")
            bad += check((page.parent / href / "index.html").is_file(),
                         f"the {source} {field} disagreement cell links to {href!r}, "
                         "which is not generated")

        # Computed, not transcribed: move one entry's path and its cell has to
        # follow. Same depth, so the cohort page's own relative links still hold.
        moved = ("title", "crossref")
        relocated = dict(cohorts[moved], path="works/title-disagreement/crossref-elsewhere/")
        render.SOURCE_DISAGREEMENT_COHORTS[moved] = relocated
        _, page, cells = render_cells(temporary / "relocated")
        cell = (cells or {}).get((relocated["source_label"], relocated["field_label"]))
        href = cell_href(cell)
        bad += check(href == f'../{relocated["path"]}',
                     f"after moving the {moved[1]} {moved[0]} cohort its cell links to {href!r}, "
                     f"not to the relocated '../{relocated['path']}'")
        bad += check(href is not None and (page.parent / href / "index.html").is_file(),
                     "the relocated cohort page is not generated where its cell points")
    finally:
        render.SOURCE_DISAGREEMENT_COHORTS.clear()
        render.SOURCE_DISAGREEMENT_COHORTS.update(cohorts)
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(temporary, ignore_errors=True)

    print("test_href_from_cohorts:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
