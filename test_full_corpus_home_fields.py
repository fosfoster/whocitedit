#!/usr/bin/env python3
"""Keep the committed legacy corpus home page on its aggregate rendering path."""
import json
import sys
from pathlib import Path

import corpus_contract
import render


ROOT = Path(__file__).parent
DATA = ROOT / "web" / "data"


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
        field_key, definition = next(iter(normalized.items()))
        derived_fields = [{
            "key": field_key,
            "name": definition["name"],
            "description": definition.get("description"),
            "works": len(works_index),
        }]
        derived_field_works = {field_key: works_index}

        if len(derived_fields) != 1:
            raise AssertionError(f"legacy derivation has {len(derived_fields)} fields, not one")
        if derived_fields[0]["works"] != len(works_index):
            raise AssertionError("derived field count does not match works-index.json")
        if derived_field_works[field_key] != works_index:
            raise AssertionError("derived legacy field does not cover every indexed work")

        aggregate_home = render.render_home(corpus, works_index, authors_index)
        derived_home = render.render_home(
            corpus, works_index, authors_index, derived_fields, derived_field_works,
        )
        if derived_home != aggregate_home:
            raise AssertionError("single-field render_home output differs from aggregate home page")
        if '<h2><a href="fields/' in derived_home:
            raise AssertionError("legacy home page carries t1 per-field section headings")
    except AssertionError as error:
        print(f"test_full_corpus_home_fields: FAILED: {error}")
        return 1

    print(f"test_full_corpus_home_fields: {len(works_index)} works audited")
    print("test_full_corpus_home_fields: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
