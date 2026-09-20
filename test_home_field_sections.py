#!/usr/bin/env python3
"""Offline coverage for per-field summary sections on the home page."""
import re
import shutil
import sys
import tempfile
from pathlib import Path

import render
from test_field_pages import write_fixture


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def section_html(home: str, key: str) -> str:
    """The home-page section for one field: from its heading to the next <h2> (or end)."""
    match = re.search(
        rf'<h2><a href="fields/{re.escape(key)}/">.*?(?=<h2>|\Z)', home, re.DOTALL,
    )
    return match.group(0) if match else ""


def member_ids(section: str) -> list:
    return re.findall(r'href="w/([^/"]+)/"', section)


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (render.DATA, render.SITE, render.ASSETS, getattr(render, "NAV_FIELDS", []))
    try:
        data = tmp / "data"
        fields, works, corpus = write_fixture(data)
        render.DATA = data
        render.SITE = tmp / "site"
        render.ASSETS = Path(__file__).parent / "web" / "assets"
        bad += check(render.main() == 0, "two-field synthetic render failed")

        home = (render.SITE / "index.html").read_text()

        expected = {
            field["key"]: [work["id"] for work in works if field["key"] in work["fields"]]
            for field in fields
        }

        # Sections must appear in fields_index order.
        positions = [home.find(f'<h2><a href="fields/{field["key"]}/">') for field in fields]
        bad += check(all(p != -1 for p in positions),
                     "home page is missing a per-field summary section heading")
        bad += check(positions == sorted(positions),
                     "per-field summary sections are not in fields_index order")

        for field in fields:
            key, name = field["key"], field["name"]
            section = section_html(home, key)
            bad += check(bool(section), f"home page has no summary section for {key}")
            bad += check(name in section, f"{key} summary section does not show the field name")
            bad += check(f'{field["works"]} papers' in section,
                         f"{key} summary section does not show its exported paper count")
            bad += check(f'href="fields/{key}/"' in section,
                         f"{key} summary section does not link to fields/{key}/")

            ids = member_ids(section)
            bad += check(ids == expected[key],
                         f"{key} summary section members are not exactly its own field members: {ids}")

            other_only = set()
            for other in fields:
                if other["key"] == key:
                    continue
                other_only |= set(expected[other["key"]]) - set(expected[key])
            bad += check(not (other_only & set(ids)),
                         f"{key} summary section leaks another field's exclusive members")
    finally:
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_home_field_sections:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
