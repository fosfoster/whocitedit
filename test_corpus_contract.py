#!/usr/bin/env python3
"""Fixture-only coverage for corpus field normalization and harvest provenance."""
import json
import shutil
import sys
import tempfile
import urllib.parse
from pathlib import Path

import corpus_contract
import harvest
import openalex


ROOT = Path(__file__).parent


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def main() -> int:
    bad = 0
    legacy = json.loads((ROOT / "corpus.json").read_text())
    legacy_key = corpus_contract.field_key(legacy["name"])
    bad += check(legacy_key == "artificial-intelligence",
                 f"legacy field key was not deterministic: {legacy_key!r}")
    normalized_legacy = corpus_contract.normalize(legacy)
    bad += check(normalized_legacy == {legacy_key: legacy},
                 "the committed legacy corpus did not retain exactly one definition")
    bad += check(normalized_legacy[legacy_key] == legacy,
                 "legacy definition values changed while normalizing")

    fields = {
        "fields": {
            "theory": {
                "name": "Theory",
                "seed_filter": "topic.id:T1",
                "seed_sort": "cited_by_count:desc",
                "max_works": 2,
            },
            "practice": {
                "name": "Practice",
                "seed_filter": "topic.id:T2",
                "seed_sort": "publication_date:asc",
                "max_works": 1,
            },
        }
    }
    bad += check(corpus_contract.normalize(fields) == fields["fields"],
                 "explicit field keys or definitions changed while normalizing")

    tmp = Path(tempfile.mkdtemp())
    real_manifest = openalex.MANIFEST
    openalex.MANIFEST = tmp / "manifest.jsonl"
    try:
        shared = {
            "results": [{"id": "https://openalex.org/W-shared"}],
            "meta": {"next_cursor": "more"},
        }
        theory_second = {
            "results": [{"id": "https://openalex.org/W-theory"}],
            "meta": {"next_cursor": "must-not-fetch"},
        }
        requested = []

        def opener(url):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            requested.append(query)
            field_filter = query["filter"][0]
            cursor = query["cursor"][0]
            if field_filter == "topic.id:T1" and cursor == "*":
                return shared
            if field_filter == "topic.id:T1" and cursor == "more":
                return theory_second
            if field_filter == "topic.id:T2" and cursor == "*":
                return shared
            raise AssertionError(f"unexpected OpenAlex request: {query}")

        client = openalex.Client(raw_dir=tmp / "raw", opener=opener,
                                 sleeper=lambda seconds: None)
        bad += check(harvest.harvest_works(client, fields) == 3,
                     "two fields did not retain their independently bounded pages")
        bad += check(
            [(q["filter"][0], q["sort"][0], q["per-page"][0], q["cursor"][0])
             for q in requested]
            == [
                ("topic.id:T1", "cited_by_count:desc", "2", "*"),
                ("topic.id:T1", "cited_by_count:desc", "1", "more"),
                ("topic.id:T2", "publication_date:asc", "1", "*"),
            ],
            f"field pagination used the wrong filter, sort, or bound: {requested}",
        )

        observations = [json.loads(line) for line in openalex.MANIFEST.read_text().splitlines()]
        bad += check([record.get("field_key") for record in observations]
                     == ["theory", "theory", "practice"],
                     "manifest observations did not retain each field key")
        bad += check(observations[0]["sha256"] == observations[2]["sha256"],
                     "the shared payload was not observed in both fields")
        raw_path = tmp / "raw" / observations[0]["sha256"][:2] / f"{observations[0]['sha256']}.json"
        expected_bytes = json.dumps(shared, sort_keys=True, separators=(",", ":")).encode()
        bad += check(raw_path.read_bytes() == expected_bytes and b"field_key" not in raw_path.read_bytes(),
                     "field provenance changed the stored source payload bytes")
    finally:
        openalex.MANIFEST = real_manifest
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_corpus_contract:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
