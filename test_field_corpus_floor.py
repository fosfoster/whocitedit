#!/usr/bin/env python3
"""Report the exported work count for every declared corpus field.

Newer exports declare their fields in ``fields-index.json``.  The committed
release predates that index, so its single field is resolved from the corpus
definition and owns every row in ``works-index.json``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import corpus_contract


ROOT = Path(__file__).parent
DATA = ROOT / "web" / "data"


def load_json(path: Path):
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def exported_fields(data: Path) -> list[dict]:
    """Resolve declared fields from the indexed or legacy export layout."""
    index_path = data / "fields-index.json"
    if index_path.is_file():
        fields = load_json(index_path)
        if not isinstance(fields, list):
            raise ValueError("fields-index.json must contain a list")
        return fields

    corpus = load_json(data / "corpus.json")
    if not isinstance(corpus, dict) or "definition" not in corpus:
        raise ValueError("corpus.json must contain a definition")
    fields = corpus_contract.normalize(corpus["definition"])
    if len(fields) != 1:
        raise ValueError("legacy field export must declare exactly one field")

    key, definition = next(iter(fields.items()))
    works = load_json(data / "works-index.json")
    if not isinstance(works, list):
        raise ValueError("works-index.json must contain a list")
    return [{
        "key": key,
        "name": definition["name"],
        "works": len(works),
    }]


def resolve_counts(fields: list[dict]) -> list[tuple[str, str, int]]:
    """Validate every declared field and return its exported work count."""
    counts = []
    keys = set()
    for field in fields:
        if not isinstance(field, dict):
            raise ValueError("field declaration must be an object")
        key = field.get("key")
        name = field.get("name")
        works = field.get("works")
        if not isinstance(key, str) or not key:
            raise ValueError("field declaration must have a non-empty key")
        if key in keys:
            raise ValueError(f"field declaration repeats {key!r}")
        if not isinstance(name, str) or not name:
            raise ValueError(f"field {key!r} must have a non-empty name")
        if isinstance(works, bool) or not isinstance(works, int) or works < 0:
            raise ValueError(f"field {key!r} must have a non-negative work count")
        keys.add(key)
        counts.append((key, name, works))
    if not counts:
        raise ValueError("field export declares no fields")
    return counts


def main() -> int:
    try:
        counts = resolve_counts(exported_fields(DATA))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        print(f"test_field_corpus_floor: FAILED: {error}", file=sys.stderr)
        return 1

    for key, name, works in counts:
        print(f"test_field_corpus_floor: {key} ({name}): {works} works")
    print("test_field_corpus_floor: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
