#!/usr/bin/env python3
"""Keep a one-field home render identical to the legacy render_home output."""
import sys

import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def single_field_fixture():
    field = {
        "key": "legacy-field",
        "name": "Legacy Field",
        "description": "A single-field fixture.",
        "works": 1,
    }
    works = [{
        "id": "W-legacy",
        "title": "Legacy paper",
        "authors": ["Legacy Author"],
        "n_authors": 1,
        "year": 2024,
        "cited": 12,
        "in_corpus_cited": 3,
    }]
    corpus = {
        "definition": {
            "name": "Legacy Fixture Field",
            "description": "A single-field fixture.",
        },
        "counts": {
            "works": 1,
            "authors": 1,
            "citations": 3,
            "coauthor_edges": 0,
            "institutions": 0,
        },
        "identity": {"high": 1, "medium": 0, "low": 0},
        "quality": {"complete": 1, "partial": 0, "suspect": 0},
    }
    return corpus, works, field


def main() -> int:
    corpus, works, field = single_field_fixture()
    legacy = render.render_home(corpus, works, [])
    with_single_field = render.render_home(
        corpus, works, [], [field], {field["key"]: works},
    )

    bad = 0
    bad += check(with_single_field == legacy,
                 "one-field render with new arguments differs from legacy three-argument output")
    for name, home in (("legacy", legacy), ("single-field", with_single_field)):
        bad += check(f'href="fields/{field["key"]}/"' not in home,
                     f"{name} home contains per-field section links")
        bad += check("Browse this field" not in home,
                     f"{name} home contains per-field section markup")

    print("test_home_single_field_legacy:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
