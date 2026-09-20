#!/usr/bin/env python3
"""render_home must stay backward compatible when called with just 3 args."""
import sys

import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def main() -> int:
    bad = 0

    corpus = {
        "definition": {"name": "Synthetic corpus", "description": "Fixture corpus."},
        "counts": {"works": 1, "authors": 1, "citations": 0,
                   "coauthor_edges": 0, "institutions": 0},
        "identity": {"high": 1, "medium": 0, "low": 0},
        "quality": {"complete": 1, "partial": 0, "suspect": 0},
    }
    works = [
        {"id": "W1", "title": "Only paper", "authors": ["A. Author"], "n_authors": 1,
         "year": 2024, "cited": 10, "in_corpus_cited": 0},
    ]
    authors = [{"id": "A1", "name": "A. Author"}]

    old_output = render.render_home(corpus, works, authors)
    new_output = render.render_home(corpus, works, authors, fields=None, field_works=None)

    bad += check(old_output == new_output,
                 "3-arg call and 5-arg call with fields=None, field_works=None diverge")

    print("test_home_signature_defaults:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
