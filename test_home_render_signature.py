#!/usr/bin/env python3
"""A single-field corpus renders the same home page it always did.

Two guarantees, against the real ``render.py`` rather than a stub:

1. ``render_home`` called with the extended five-argument form and a
   one-entry ``fields_index`` returns bytes identical to the legacy
   three-argument call.  One field is not a reason to render anything new.
2. A legacy full render through ``render.main()`` -- the committed release's
   shape, with no ``fields-index.json`` and no ``fields`` on any row -- writes
   a home page with no per-field section markup: outside the chrome field
   navigation, nothing on it links a specific ``fields/<key>/`` page.
"""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import corpus_contract
import render
from test_legacy_field_membership import index_row, write_fixture


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def first_difference(left: bytes, right: bytes) -> str:
    for i, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return f"byte {i}: {left[i:i + 60]!r} != {right[i:i + 60]!r}"
    return f"lengths differ: {len(left)} != {len(right)}"


def without_field_nav(home: str) -> str:
    """The home page minus the chrome field navigation every page carries."""
    return re.sub(r'<nav class="field-nav".*?</nav>', "", home, flags=re.S)


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (render.DATA, render.SITE, render.ASSETS, getattr(render, "NAV_FIELDS", []))
    try:
        render.ASSETS = Path(__file__).parent / "web" / "assets"

        definition = {
            "name": "Artificial Intelligence & Robotics",
            "description": "One legacy field.",
            "max_works": 3,
        }
        legacy_key = corpus_contract.field_key(definition["name"])
        works = [
            index_row("W-legacy-first", "Legacy first", 2024),
            index_row("W-legacy-second", "Legacy second", 2023),
            index_row("W-legacy-third", "Legacy third", 2022),
        ]
        data = tmp / "legacy-data"
        write_fixture(data, definition, works)
        bad += check(not (data / "fields-index.json").exists()
                     and all("fields" not in row for row in works),
                     "legacy fixture was not written without any field export surface")

        render.DATA = data
        render.SITE = tmp / "legacy-site"
        bad += check(render.main() == 0, "legacy single-field render failed")

        # (a) The same call, both signatures.  main() derives exactly this
        # one-entry fields_index and field_works for a legacy corpus.
        corpus = json.loads((data / "corpus.json").read_text())
        works_index = json.loads((data / "works-index.json").read_text())
        authors_index = json.loads((data / "authors-index.json").read_text())
        fields_index = [{
            "key": legacy_key,
            "name": definition["name"],
            "description": definition.get("description"),
            "works": len(works_index),
        }]
        field_works = {legacy_key: works_index}
        render.NAV_FIELDS = fields_index

        legacy_call = render.render_home(corpus, works_index, authors_index).encode()
        extended_call = render.render_home(
            corpus, works_index, authors_index, fields_index, field_works).encode()
        bad += check(
            legacy_call == extended_call,
            "single-field five-argument render_home is not byte-identical to the "
            f"three-argument call -- {first_difference(legacy_call, extended_call)}",
        )

        # (b) The legacy full render carries no per-field section markup.
        home = (render.SITE / "index.html").read_text()
        body = without_field_nav(home)
        bad += check('<nav class="field-nav"' in home,
                     "fixture changed: the home page no longer carries the chrome field nav")
        field_links = sorted(set(re.findall(r'href="(fields/[^"]*)"', body)))
        bad += check(field_links == ["fields/"],
                     f"legacy home page links field pages outside the chrome nav: {field_links}")
        bad += check(not re.search(r"<h2>\s*<a href=\"fields/", body),
                     "legacy home page has a per-field section heading")
        bad += check(legacy_key not in body,
                     f"legacy home page names the field {legacy_key} outside the chrome nav")
    finally:
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_home_render_signature:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
