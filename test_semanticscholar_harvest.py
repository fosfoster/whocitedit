#!/usr/bin/env python3
"""Fixture-only test for Semantic Scholar's stored-OpenAlex DOI harvest."""
import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

import harvest


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    real_root = harvest.ROOT
    try:
        harvest.ROOT = tmp
        raw = tmp / "harvest" / "raw"
        raw.mkdir(parents=True)

        # These are stored OpenAlex work pages. Equivalent resolver and
        # doi: forms must lead to one Semantic Scholar request.
        (raw / "openalex-works.json").write_text(json.dumps({"results": [
            {"id": "https://openalex.org/W1",
             "doi": "https://doi.org/10.5555/source-paper", "authorships": []},
            {"id": "https://openalex.org/W2",
             "doi": "doi:10.5555/source-paper", "authorships": []},
            {"id": "https://openalex.org/W3",
             "doi": "10.1111/earlier-paper", "authorships": []},
            {"id": "https://openalex.org/W4", "doi": None, "authorships": []},
        ]}))

        # Other retained source shapes may name a DOI, but are not OpenAlex
        # work pages and must not turn into visits.
        (raw / "semanticscholar.json").write_text(json.dumps({
            "externalIds": {"DOI": "10.9999/already-harvested"},
            "references": [],
        }))
        (raw / "openalex-authors.json").write_text(json.dumps({"results": [
            {"doi": "10.9999/not-a-work"},
        ]}))
        (raw / "other-list.json").write_text(json.dumps([
            {"doi": "10.9999/not-a-work"},
        ]))

        harvested = []

        class RecordingClient:
            def __init__(self):
                self.spent = 0

            def references(self, doi):
                harvested.append(doi)
                self.spent += 1

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            count = harvest.harvest_semanticscholar(RecordingClient())

        expected = ["10.1111/earlier-paper", "10.5555/source-paper"]
        bad += check(count == 2, "harvest did not return its exact DOI count")
        bad += check(harvested == expected,
                     "harvest did not normalize, deduplicate, and sort OpenAlex DOIs")
        bad += check(
            "semanticscholar 1/2  (1 requests)" in output.getvalue()
            and "semanticscholar 2/2  (2 requests)" in output.getvalue(),
            "harvest did not report incremental Semantic Scholar request usage",
        )
    finally:
        harvest.ROOT = real_root
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_semanticscholar_harvest:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
