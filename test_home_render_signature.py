#!/usr/bin/env python3
"""A single-field corpus renders the same home page it always did.

Two guarantees, against the real ``render.py`` rather than a stub, driven by
one ``render.main()`` over the committed release's shape -- one top-level
definition, no ``fields-index.json``, no ``fields`` on any index row.

1. BYTE IDENTITY.  The five-argument ``render_home`` call ``main()`` actually
   makes -- its own ``fields_index``/``field_works``, captured off the call
   rather than rebuilt here -- returns bytes identical to the legacy
   three-argument call on the same corpus.  One field is not a reason to
   render anything new.
2. NO PER-FIELD SECTION MARKUP.  The home page that render writes carries
   nothing field-scoped outside the chrome field navigation every page has:
   no second link to a ``fields/<key>/`` page, and the field's key nowhere on
   it.  A per-field summary section cannot exist without one of those.
"""
import inspect
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


def recorded_render(calls: list) -> int:
    """``render.main()`` with every ``render_home`` call recorded as bound
    arguments, so the test asserts against the call main() makes rather than
    against a second copy of how main() builds it."""
    real = render.render_home
    signature = inspect.signature(real)

    def recording(*args, **kwargs):
        calls.append(signature.bind(*args, **kwargs))
        return real(*args, **kwargs)

    render.render_home = recording
    try:
        return render.main()
    finally:
        render.render_home = real


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
        calls = []
        bad += check(recorded_render(calls) == 0, "legacy single-field render failed")
        bad += check(len(calls) == 1,
                     f"render.main() called render_home {len(calls)} times, expected 1")
        if not calls:
            return 1

        # (a) The same call, both signatures.
        passed = calls[0].arguments
        bad += check("fields_index" in passed and "field_works" in passed,
                     "render.main() still calls render_home with the legacy three "
                     f"arguments: it passed {sorted(passed)}")
        if "fields_index" not in passed or "field_works" not in passed:
            return 1

        fields_index, field_works = passed["fields_index"], passed["field_works"]
        bad += check([field["key"] for field in fields_index] == [legacy_key],
                     "a legacy corpus did not reach render_home as one normalized "
                     f"field: {[field.get('key') for field in fields_index]}")
        bad += check(sorted(field_works) == [legacy_key],
                     f"field_works is not the one legacy field: {sorted(field_works)}")

        extended_call = render.render_home(*calls[0].args, **calls[0].kwargs).encode()
        legacy_call = render.render_home(
            passed["corpus"], passed["works"], passed["authors"]).encode()
        bad += check(
            legacy_call == extended_call,
            "single-field five-argument render_home is not byte-identical to the "
            f"three-argument call -- {first_difference(legacy_call, extended_call)}",
        )

        # (b) The legacy full render carries no per-field section markup.
        home = (render.SITE / "index.html").read_text()
        bad += check(home.encode() == extended_call,
                     "the home page on disk is not what render_home returned")
        bad += check('<nav class="field-nav"' in home,
                     "fixture changed: the home page no longer carries the chrome field nav")
        body = without_field_nav(home)
        field_links = sorted(set(re.findall(r'href="(fields/[^"]*)"', body)))
        bad += check(field_links == ["fields/"],
                     f"legacy home page links field pages outside the chrome nav: {field_links}")
        bad += check(legacy_key not in body,
                     f"legacy home page names the field {legacy_key} outside the chrome nav")
        field_classes = re.findall(r'<\w+[^>]*class="[^"]*\bfield[\w-]*"', body)
        bad += check(not field_classes,
                     f"legacy home page carries field-scoped markup: {field_classes}")
    finally:
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_home_render_signature:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
