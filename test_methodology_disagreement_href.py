#!/usr/bin/env python3
"""Every methodology disagreement cell links to the route its own
SOURCE_DISAGREEMENT_COHORTS entry declares, and that entry is the only place
render.py declares it.

Two separate claims, because a hard-coded href and a derived one look the same
in one rendered page: the six cells match the declared routes, and rewriting a
cohort's `path` moves its cell. A second route map would survive the first
check and fail the second.
"""
import json
import re
import sys
from pathlib import Path

import render


DATA = Path(__file__).parent / "web" / "data"


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def comparison_cells(html):
    """Map (source label, field label) to each row's three rendered count cells."""
    panel = re.search(
        r"<h2>Source record field comparisons</h2>.*?<tbody>(.*?)</tbody>", html, re.S,
    )
    if panel is None:
        return None
    rows = re.findall(
        r'<tr><td>(.*?)</td><td>(.*?)</td><td class="num">(.*?)</td>'
        r'<td class="num">(.*?)</td><td class="num">(.*?)</td></tr>',
        panel.group(1),
    )
    return {(source, field): counts for source, field, *counts in rows}


def render_cells(cohorts):
    """Render the methodology page against `cohorts` and return its count cells."""
    corpus = json.loads((DATA / "corpus.json").read_text())
    counts = {key: {"comparable": 2, "agreeing": 1, "disagreeing": 1} for key in cohorts}
    saved = render.SOURCE_DISAGREEMENT_COHORTS
    try:
        render.SOURCE_DISAGREEMENT_COHORTS = cohorts
        return comparison_cells(render.render_methodology(corpus, counts))
    finally:
        render.SOURCE_DISAGREEMENT_COHORTS = saved


def main() -> int:
    bad = 0
    cohorts = render.SOURCE_DISAGREEMENT_COHORTS
    bad += check(
        len(cohorts) == 6,
        f"SOURCE_DISAGREEMENT_COHORTS declares {len(cohorts)} cohorts; "
        "the methodology matrix is three fields against two sources",
    )

    # Each cohort's route is declared once, in SOURCE_DISAGREEMENT_COHORTS.
    # A duplicate route map would repeat the literal.
    render_source = Path(render.__file__).read_text()
    for config in cohorts.values():
        occurrences = render_source.count(config["path"])
        bad += check(
            occurrences == 1,
            f'render.py names the route {config["path"]!r} {occurrences} times; '
            "SOURCE_DISAGREEMENT_COHORTS should be its only declaration",
        )

    cells = render_cells(cohorts)
    bad += check(cells is not None, "methodology renders no source-field comparison table")
    cells = cells or {}
    bad += check(
        len(cells) == len(cohorts),
        f"methodology renders {len(cells)} source-field rows, expected {len(cohorts)}",
    )

    for config in cohorts.values():
        label = (config["source_label"], config["field_label"])
        row = cells.get(label)
        bad += check(row is not None, f"no disagreement cell rendered for {label}")
        if row is None:
            continue
        comparable, agreeing, cell = row
        # The disagreement count is the cell that leads to the cohort page;
        # comparable and agreeing have no page of their own to link to.
        bad += check(
            "<a " not in comparable and "<a " not in agreeing,
            f"the {label} comparable/agreeing counts became links: "
            f"{comparable!r}, {agreeing!r}",
        )
        link = re.fullmatch(r'<a href="([^"]+)">(.*)</a>', cell)
        bad += check(link is not None, f"the {label} disagreement cell carries no href: {cell!r}")
        if link is None:
            continue
        bad += check(
            link.group(1) == f'../{config["path"]}',
            f'the {label} disagreement cell links to {link.group(1)!r}, not to its '
            f'SOURCE_DISAGREEMENT_COHORTS route {"../" + config["path"]!r}',
        )
        bad += check(
            link.group(2) == render.num(1),
            f"the {label} disagreement link lost its count: {cell!r}",
        )

    # Rewrite every route and the cells must follow, which a second map holding
    # the original routes could not do.
    moved = {
        key: {**config, "path": f'moved/{config["path"]}'}
        for key, config in cohorts.items()
    }
    moved_cells = render_cells(moved) or {}
    for config in moved.values():
        label = (config["source_label"], config["field_label"])
        cell = moved_cells.get(label, ("", "", ""))[2]
        bad += check(
            f'href="../{config["path"]}"' in cell,
            f'the {label} disagreement cell ignored its rewritten '
            f'SOURCE_DISAGREEMENT_COHORTS route {config["path"]!r}: {cell!r}',
        )

    print("test_methodology_disagreement_href:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
