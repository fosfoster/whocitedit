#!/usr/bin/env python3
"""Offline coverage for the home page's per-field summary sections."""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import render
from test_field_pages import write_fixture


def check(condition: bool, message: str) -> int:
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def sections(home: str) -> list[tuple[str, str]] | None:
    """Split the per-field region between the corpus panel and Most cited."""
    panel = re.search(
        r'<div class="panel">\s*<h2>What this corpus is, exactly</h2>.*?</div>',
        home,
        re.DOTALL,
    )
    most_cited = home.find("<h2>Most cited</h2>")
    if panel is None or most_cited < panel.end():
        return None
    region = home[panel.end():most_cited]
    headings = list(re.finditer(
        r'<h2><a href="fields/([^/"]+)/">', region,
    ))
    bounds = [heading.start() for heading in headings] + [len(region)]
    return [
        (heading.group(1), region[bounds[i]:bounds[i + 1]])
        for i, heading in enumerate(headings)
    ]


def member_ids(section: str) -> list[str]:
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
        bad += check(render.main() == 0, "multi-field synthetic render failed")

        site = render.SITE
        home = (site / "index.html").read_text()
        expected = {
            field["key"]: [work["id"] for work in works if field["key"] in work["fields"]]
            for field in fields
        }
        found = sections(home)
        bad += check(found is not None, "home page has no per-field region to read")
        found = found or []
        bad += check([key for key, _ in found] == [field["key"] for field in fields],
                     f"home sections are not one per field in fields-index order: "
                     f"{[key for key, _ in found]}")

        for field, (key, section) in zip(fields, found):
            bad += check(key == field["key"], f"section {key} is out of order")
            bad += check(field["name"] in section,
                         f"{key}'s section does not name the field")
            bad += check(f'href="fields/{key}/"' in section,
                         f"{key}'s section does not link fields/{key}/")
            bad += check((site / "fields" / key / "index.html").exists(),
                         f"{key}'s field link lacks its canonical route")
            bad += check(f'{render.num(field["works"])} papers' in section,
                         f"{key}'s section does not render its exported count")
            if field["description"]:
                bad += check(field["description"] in section,
                             f"{key}'s section does not render its exported description")
            ids = member_ids(section)
            bad += check(ids == expected[key][:5],
                         f"{key}'s section members are not its top membership in order: {ids}")
            outside = [work["id"] for work in works if key not in work["fields"]]
            bad += check(not [wid for wid in ids if wid in outside],
                         f"{key}'s section links a work that is not one of its members")
            for wid in ids:
                bad += check((site / "w" / wid / "index.html").exists(),
                             f"{key}'s section link lacks canonical w/{wid}/ route")

        # The exported count leads; a field without one falls back to the length
        # of its membership. The member list stays short however long that is.
        many = [dict(work, id=f"W-many-{i}", title=f"Many {i}")
                for i, work in enumerate(works * 3)]
        uncounted = [{"key": "alpha", "name": "Alpha Field"},
                     {"key": "zeta", "name": "Zeta Field", "works": 3}]
        mixed = sections(render.render_home(corpus, works, [], uncounted,
                                            {"alpha": many, "zeta": []}))
        bad += check(len(mixed or []) == 2, "a mixed two-field call lost a section")
        if mixed and len(mixed) == 2:
            bad += check(member_ids(mixed[0][1]) == [work["id"] for work in many[:5]],
                         "an oversized field is not cut to a short member list")
            bad += check(f"{render.num(len(many))} papers" in mixed[0][1],
                         "a field without an exported count does not fall back to membership")
            bad += check(f"{render.num(3)} papers" in mixed[1][1]
                         and not member_ids(mixed[1][1]),
                         "an exported count is not preferred over an empty membership")

        # One field is the shipped release: passing the new arguments must not
        # change even one character of the aggregate page.
        single = [dict(fields[0])]
        bad += check(
            render.render_home(corpus, works, [])
            == render.render_home(corpus, works, [], single, {fields[0]["key"]: works}),
            "a single-field call does not return the aggregate page byte for byte",
        )

        # The same guarantee holds through a complete legacy render, which has
        # neither fields-index.json nor per-work membership arrays.
        legacy = tmp / "legacy-data"
        shutil.copytree(data, legacy)
        (legacy / "fields-index.json").unlink()
        legacy_works = json.loads((legacy / "works-index.json").read_text())
        for work in legacy_works:
            work.pop("fields")
        (legacy / "works-index.json").write_text(json.dumps(legacy_works))
        legacy_corpus = dict(corpus)
        legacy_corpus["definition"] = {
            "name": "Legacy Fixture Field",
            "description": "One old field.",
        }
        legacy_corpus.pop("fields")
        (legacy / "corpus.json").write_text(json.dumps(legacy_corpus))
        render.DATA = legacy
        render.SITE = tmp / "legacy-site"
        bad += check(render.main() == 0, "legacy single-field render failed")
        legacy_home = (render.SITE / "index.html").read_text()
        bad += check(sections(legacy_home) == [],
                     "legacy home page carries per-field summary markup")
        bad += check('<h2><a href="fields/' not in legacy_home,
                     "legacy home page carries a per-field heading outside the target region")
        bad += check(
            legacy_home == render.render_home(legacy_corpus, legacy_works, []),
            "legacy full render is not the untouched three-argument aggregate page",
        )
    finally:
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_home_field_sections:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
