#!/usr/bin/env python3
"""Keep the committed legacy corpus home page on its aggregate rendering path."""
from contextlib import contextmanager
import json
import shutil
import sys
import tempfile
from pathlib import Path

import corpus_contract
import render


ROOT = Path(__file__).parent
DATA = ROOT / "web" / "data"
ASSETS = ROOT / "web" / "assets"


@contextmanager
def rendered_home():
    """Run the real legacy render path and expose its home-page inputs."""
    saved = render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS, render.render_home
    temporary = Path(tempfile.mkdtemp())
    captured = {}

    def capture_home(corpus, works, authors, fields=None, field_works=None):
        home = saved[4](corpus, works, authors, fields, field_works)
        aggregate_home = saved[4](corpus, works, authors)
        captured.update(
            fields=fields,
            field_works=field_works,
            home=home,
            aggregate_home=aggregate_home,
        )
        return home

    try:
        render.DATA = DATA
        render.SITE = temporary / "site"
        render.ASSETS = ASSETS
        render.render_home = capture_home
        if render.main() != 0:
            raise AssertionError("render.main() failed for the committed corpus")
        yield render.SITE / "index.html", captured
    finally:
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS, render.render_home = saved
        shutil.rmtree(temporary, ignore_errors=True)


def main() -> int:
    corpus = json.loads((DATA / "corpus.json").read_text())
    works_index = json.loads((DATA / "works-index.json").read_text())
    authors_index = json.loads((DATA / "authors-index.json").read_text())

    try:
        if (DATA / "fields-index.json").exists():
            raise AssertionError("committed corpus is no longer a legacy release: fields-index.json exists")
        if any("fields" in work for work in works_index):
            raise AssertionError("committed corpus is no longer a legacy release: work fields exist")
        normalized = corpus_contract.normalize(corpus["definition"])
        if len(normalized) != 1:
            raise AssertionError(f"legacy definition normalized to {len(normalized)} fields, not one")
        expected_field_key = next(iter(normalized))

        with rendered_home() as (home_path, captured):
            generated_home = home_path.read_text()

        derived_fields = captured["fields"]
        derived_field_works = captured["field_works"]
        if len(derived_fields) != 1:
            raise AssertionError(f"render.main derived {len(derived_fields)} fields, not one")
        field_key = derived_fields[0]["key"]
        if field_key != expected_field_key:
            raise AssertionError("render.main did not derive the normalized legacy field key")
        if derived_fields[0]["works"] != len(works_index):
            raise AssertionError("derived field count does not match works-index.json")
        if set(derived_field_works) != {field_key}:
            raise AssertionError("render.main did not derive exactly one field membership list")
        if derived_field_works[field_key] != works_index:
            raise AssertionError("render.main's legacy field does not cover every indexed work")

        if generated_home != captured["home"]:
            raise AssertionError("generated index.html differs from render.main's home output")
        if generated_home != captured["aggregate_home"]:
            raise AssertionError("legacy render.main home differs from aggregate home page")
        if '<h2><a href="fields/' in generated_home:
            raise AssertionError("legacy home page carries t1 per-field section headings")
    except AssertionError as error:
        print(f"test_full_corpus_home_fields: FAILED: {error}")
        return 1

    print(f"test_full_corpus_home_fields: {len(works_index)} works audited")
    print("test_full_corpus_home_fields: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
