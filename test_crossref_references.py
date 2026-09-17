#!/usr/bin/env python3
"""Fixture-only tests for Crossref reference fetch and DOI extraction."""
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import crossref
from crossref import Client, reference_dois


ROOT = Path(__file__).parent
FIXTURE = json.loads(
    (ROOT / "docs" / "fixtures" / "crossref" / "work-references.json").read_text()
)


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    manifest = tmp / "manifest.jsonl"
    real_manifest = crossref.MANIFEST
    crossref.MANIFEST = manifest
    try:
        calls = []

        def fixture_opener(url):
            calls.append(url)
            return FIXTURE

        c = Client(mailto="t@example.com", raw_dir=tmp / "raw", opener=fixture_opener,
                   sleeper=lambda seconds: None, clock=lambda: 0.0)
        fetched = c.references("https://doi.org/10.5555/source-paper")
        expected_url = f"{crossref.BASE}/10.5555%2Fsource-paper?mailto=t%40example.com"
        bad += check(fetched.url == expected_url and calls == [expected_url],
                     "DOI was not safely encoded into the Crossref references request")

        # Storage is complete before the returned object names it: canonical
        # bytes, their exact SHA-256 filename, and full manifest provenance,
        # via the same _store() path as work().
        expected_sha = hashlib.sha256(
            json.dumps(FIXTURE, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        record = json.loads(manifest.read_text().strip())
        bad += check(fetched.payload == FIXTURE and fetched.sha256 == expected_sha
                     and fetched.path.name == f"{expected_sha}.json"
                     and json.loads(fetched.path.read_text()) == FIXTURE,
                     "Crossref references response was not retained under its canonical hash")
        bad += check(record["url"] == expected_url and record["sha256"] == expected_sha
                     and record["path"] == str(fetched.path) and record["fetched_at"]
                     and set(record) == {"url", "sha256", "path", "fetched_at"},
                     "manifest lost Crossref references observation provenance")

        # The budget is charged exactly once per references() call, same cost
        # as work().
        bad += check(c.spent == crossref.REQUEST_COST,
                     "references() did not charge the standard request budget once")

        # reference_dois() normalizes, deduplicates, preserves first-seen
        # order, and skips unstructured entries and rejected DOIs.
        expected_dois = [
            "10.5555/reference-one",
            "10.5555/reference-two",
            "10.5555/source-paper",
            "10.5555/does-not-exist",
        ]
        bad += check(reference_dois(FIXTURE) == expected_dois,
                     "reference_dois() did not normalize, dedupe, and order-stabilize")
    finally:
        crossref.MANIFEST = real_manifest
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_crossref_references:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
