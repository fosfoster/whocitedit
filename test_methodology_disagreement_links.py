#!/usr/bin/env python3
"""Follow every methodology disagreement count to its complete static cohort."""
import re
import shutil
import sys
import tempfile
from pathlib import Path

import render
from test_methodology_source_matrix import write_fixture


EXPECTED_MEMBERS = {
    ("title", "crossref"): ["W-CROSSREF-TITLE"],
    ("title", "europepmc"): ["W-EUROPEPMC-TITLE"],
    ("venue", "crossref"): ["W-BOTH-VENUE"],
    ("venue", "europepmc"): ["W-BOTH-VENUE"],
    ("date", "crossref"): ["W-CROSSREF-DATE"],
    ("date", "europepmc"): [],
}


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def matrix_rows(html):
    panel = re.search(
        r'<h2>Source record field comparisons</h2>.*?<tbody>(.*?)</tbody>', html, re.S,
    )
    if panel is None:
        return []
    return re.findall(
        r'<tr><td>(.*?)</td><td>(.*?)</td><td class="num">.*?</td>'
        r'<td class="num">.*?</td>'
        r'<td class="num">(.*?)</td></tr>',
        panel.group(1),
        re.S,
    )


def cohort_work_links(html):
    table = re.search(r"<tbody>(.*?)</tbody>", html, re.S)
    if table is None:
        return []
    return re.findall(r'<a href="(\.\./\.\./\.\./w/[^"/]+/)">', table.group(1))


def main():
    bad = 0
    temporary = Path(tempfile.mkdtemp())
    saved = render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS
    saved_paths = {
        cohort: config["path"]
        for cohort, config in render.SOURCE_DISAGREEMENT_COHORTS.items()
    }
    try:
        for number, config in enumerate(render.SOURCE_DISAGREEMENT_COHORTS.values(), 1):
            config["path"] = f"works/config-route-{number}/cohort/"

        data = temporary / "data"
        write_fixture(data)
        render.DATA = data
        render.SITE = temporary / "site"
        render.ASSETS = Path(__file__).parent / "web" / "assets"
        bad += check(render.main() == 0, "synthetic render failed")

        methodology = render.SITE / "methodology" / "index.html"
        bad += check(methodology.is_file(), "methodology index was not generated")
        html = methodology.read_text() if methodology.is_file() else ""
        rows = matrix_rows(html)
        bad += check(
            len(rows) == len(render.SOURCE_DISAGREEMENT_COHORTS),
            "methodology does not contain exactly six disagreement cells",
        )

        rows_by_label = {}
        for source_label, field_label, cell in rows:
            rows_by_label.setdefault((source_label, field_label), []).append(cell)

        for cohort, config in render.SOURCE_DISAGREEMENT_COHORTS.items():
            field, source = cohort
            label = (config["source_label"], config["field_label"])
            cells = rows_by_label.get(label, [])
            bad += check(len(cells) == 1, f"{source}/{field} has no single matrix cell")
            if len(cells) != 1:
                continue

            anchor = re.fullmatch(
                r'<a href="([^"]+)">([0-9][0-9,]*)</a>', cells[0],
            )
            bad += check(anchor is not None, f"{source}/{field} count is not an ordinary anchor")
            if anchor is None:
                continue

            href, count_text = anchor.groups()
            linked_count = int(count_text.replace(",", ""))
            expected_href = f'../{config["path"]}'
            bad += check(
                href == expected_href,
                f"{source}/{field} links to {href!r}, expected configured {expected_href!r}",
            )

            destination = (methodology.parent / href / "index.html").resolve()
            configured_destination = (render.SITE / config["path"] / "index.html").resolve()
            bad += check(
                destination == configured_destination,
                f"{source}/{field} href does not resolve to its configured cohort",
            )
            bad += check(destination.is_file(), f"{source}/{field} destination index is missing")
            if not destination.is_file():
                continue

            destination_html = destination.read_text()
            work_hrefs = cohort_work_links(destination_html)
            member_ids = [href.rstrip("/").rsplit("/", 1)[-1] for href in work_hrefs]
            expected_members = EXPECTED_MEMBERS[cohort]
            bad += check(
                linked_count == len(member_ids),
                f"{source}/{field} linked count {linked_count} != destination membership {len(member_ids)}",
            )
            bad += check(
                member_ids == expected_members,
                f"{source}/{field} reaches {member_ids!r}, expected {expected_members!r}",
            )
            for work_href in work_hrefs:
                work_page = (destination.parent / work_href / "index.html").resolve()
                bad += check(work_page.is_file(), f"{source}/{field} has a broken {work_href} link")
            if not expected_members:
                bad += check(linked_count == 0, f"{source}/{field} empty cohort count is not zero")
                bad += check(
                    "No works in this release match this disagreement cohort." in destination_html,
                    f"{source}/{field} empty destination has no explicit empty state",
                )
    finally:
        for cohort, path in saved_paths.items():
            render.SOURCE_DISAGREEMENT_COHORTS[cohort]["path"] = path
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(temporary, ignore_errors=True)

    print("test_methodology_disagreement_links:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
