#!/usr/bin/env python3
"""main() hands render_home the field index and memberships it already computes.

``render_home`` never reads ``web/data``, so anything per-field it renders has to
arrive as an argument.  This drives ``render.main()`` over both corpus shapes -- a
multi-field export, and a legacy release with neither ``fields-index.json`` nor
work memberships -- with ``render_home``, ``render_fields`` and ``render_field``
recorded, and compares the home page's arguments against the field index and
member lists main() handed the /fields/ pages rather than against either alone.
"""
import inspect
import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

import corpus_contract
import render
from test_field_pages import write_fixture

REAL_HOME = render.render_home
REAL_FIELDS = render.render_fields
REAL_FIELD = render.render_field


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def bound(func, call):
    """One recorded call's arguments by name, however main() passed them."""
    arguments = inspect.signature(func).bind(*call.args, **call.kwargs)
    arguments.apply_defaults()
    return arguments.arguments


def write_legacy(data: Path, legacy: Path, definition: dict):
    """Copy a fixture into the pre-membership release shape."""
    shutil.copytree(data, legacy)
    (legacy / "fields-index.json").unlink()
    works = json.loads((legacy / "works-index.json").read_text())
    for work in works:
        work.pop("fields")
    (legacy / "works-index.json").write_text(json.dumps(works))
    corpus = json.loads((legacy / "corpus.json").read_text())
    corpus.pop("fields")
    corpus["definition"] = definition
    (legacy / "corpus.json").write_text(json.dumps(corpus))
    return works


def observe(label, data: Path, site: Path, expected_works, expected_fields, expected_field_works):
    """Render `data` and check what render_home was told about the fields."""
    bad = 0
    render.DATA = data
    render.SITE = site
    with mock.patch.object(render, "render_home", wraps=render.render_home) as home, \
            mock.patch.object(render, "render_fields", wraps=render.render_fields) as listing, \
            mock.patch.object(render, "render_field", wraps=render.render_field) as pages:
        result = render.main()

    bad += check(result == 0, f"{label}: render.main() returned {result}")
    bad += check(home.call_count == 1,
                 f"{label}: render_home was called {home.call_count} times, not once")
    if not home.call_count:
        return bad

    home_args = bound(REAL_HOME, home.call_args)
    bad += check(home_args.get("fields") == expected_fields,
                 f"{label}: render_home's fields argument is {home_args.get('fields')!r}, "
                 "not the fields index main() computed")
    bad += check(home_args.get("field_works") == expected_field_works,
                 f"{label}: render_home's field_works argument is "
                 f"{home_args.get('field_works')!r}, not the field-key-to-works map "
                 "main() computed")
    bad += check(home_args.get("works") == expected_works
                 and home_args.get("authors") == [],
                 f"{label}: render_home's existing works and authors arguments changed")

    # The same two values reach the /fields/ pages, so read them back off those
    # calls instead of trusting the expectations above on their own.
    bad += check(listing.call_count == 1,
                 f"{label}: render_fields was called {listing.call_count} times, not once")
    if listing.call_count:
        bad += check(home_args.get("fields") == bound(REAL_FIELDS, listing.call_args)["fields"],
                     f"{label}: render_home and render_fields were given different "
                     "field indexes")
    rendered = {}
    for call in pages.call_args_list:
        field_args = bound(REAL_FIELD, call)
        rendered[field_args["field"]["key"]] = field_args["works"]
    bad += check(home_args.get("field_works") == rendered,
                 f"{label}: render_home's field_works disagrees with the members main() "
                 f"rendered on the field pages: {sorted(rendered)}")
    bad += check((site / "index.html").exists(),
                 f"{label}: no home page was written")
    return bad


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (render.DATA, render.SITE, render.ASSETS, getattr(render, "NAV_FIELDS", []))
    try:
        render.ASSETS = Path(__file__).parent / "web" / "assets"

        # A multi-field export: the index is fields-index.json and every field
        # owns the indexed works that name its key.
        data = tmp / "data"
        exported_fields, works, _ = write_fixture(data)
        bad += observe(
            "multi-field",
            data,
            tmp / "site",
            works,
            exported_fields,
            {field["key"]: [work for work in works if field["key"] in work["fields"]]
             for field in exported_fields},
        )

        # A legacy release: one field normalized from the top-level definition,
        # owning every indexed work.
        definition = {"name": "Legacy Fixture Field", "description": "One old field."}
        legacy = tmp / "legacy-data"
        legacy_works = write_legacy(data, legacy, definition)
        legacy_key = corpus_contract.field_key(definition["name"])
        bad += observe(
            "legacy",
            legacy,
            tmp / "legacy-site",
            legacy_works,
            [{"key": legacy_key, "name": definition["name"],
              "description": definition["description"], "works": len(legacy_works)}],
            {legacy_key: legacy_works},
        )
    finally:
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_main_passes_fields:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
