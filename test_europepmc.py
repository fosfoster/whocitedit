#!/usr/bin/env python3
"""Fixture-only tests for Europe PMC retention and request construction."""
import hashlib
import json
import shutil
import sys
import tempfile
import urllib.error
from pathlib import Path

import europepmc
from europepmc import BudgetExhausted, Client, normalize_doi


ROOT = Path(__file__).parent
SEARCH_FIXTURE = json.loads(
    (ROOT / "docs" / "fixtures" / "europepmc" / "search.json").read_text()
)
REFERENCES_FIXTURE = json.loads(
    (ROOT / "docs" / "fixtures" / "europepmc" / "references.json").read_text()
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
    real_manifest = europepmc.MANIFEST
    europepmc.MANIFEST = manifest
    try:
        calls = []

        def fixture_opener(url):
            calls.append(url)
            if "/references" in url:
                return REFERENCES_FIXTURE
            return SEARCH_FIXTURE

        c = Client(raw_dir=tmp / "raw", opener=fixture_opener,
                   sleeper=lambda seconds: None, clock=lambda: 0.0)

        # (a) A DOI is safely encoded into the search request: the quoted
        # query term is urlencoded, so punctuation cannot become URL or query
        # structure.
        fetched = c.search("https://doi.org/10.5555/source-paper")
        expected_query = 'query=DOI%3A%2210.5555%2Fsource-paper%22&format=json&resultType=core'
        expected_url = f"{europepmc.BASE}/search?{expected_query}"
        bad += check(fetched.url == expected_url and calls == [expected_url],
                     "DOI was not safely encoded into the Europe PMC search request")
        bad += check(c._search_url('10.5555/source paper?query')
                     .startswith(f"{europepmc.BASE}/search?query=DOI%3A%2210.5555%2Fsource"),
                     "DOI punctuation escaped the Europe PMC search query")
        bad += check(normalize_doi("doi:10.5555/source-paper") == "10.5555/source-paper",
                     "DOI normalization failed")

        # (b) The response is stored under its exact canonical SHA-256 with a
        # complete manifest record.
        expected_sha = hashlib.sha256(
            json.dumps(SEARCH_FIXTURE, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        record = json.loads(manifest.read_text().strip())
        bad += check(fetched.payload == SEARCH_FIXTURE and fetched.sha256 == expected_sha
                     and fetched.path.name == f"{expected_sha}.json"
                     and json.loads(fetched.path.read_text()) == SEARCH_FIXTURE,
                     "Europe PMC search response was not retained under its canonical hash")
        bad += check(record["url"] == expected_url and record["sha256"] == expected_sha
                     and record["path"] == str(fetched.path) and record["fetched_at"]
                     and set(record) == {"url", "sha256", "path", "fetched_at"},
                     "manifest lost Europe PMC search observation provenance")

        # references() hits /{source}/{id}/references and is stored the same way.
        refs = c.references("MED", "38000001")
        expected_refs_url = f"{europepmc.BASE}/MED/38000001/references?format=json"
        expected_refs_sha = hashlib.sha256(
            json.dumps(REFERENCES_FIXTURE, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        bad += check(refs.url == expected_refs_url and refs.payload == REFERENCES_FIXTURE
                     and refs.sha256 == expected_refs_sha,
                     "Europe PMC references request or storage was incorrect")

        # (c) A zero-budget client raises BudgetExhausted before the opener
        # is called.
        refused = []
        small = Client(raw_dir=tmp / "small", budget=0,
                       opener=lambda url: refused.append(url) or SEARCH_FIXTURE,
                       sleeper=lambda seconds: None)
        try:
            small.search("10.5555/source-paper")
            bad += check(False, "a request was allowed with no remaining budget")
        except BudgetExhausted:
            pass
        bad += check(small.spent == 0 and not refused, "budget refusal charged or transported")

        # (d) A 429 then success is retried.
        attempts = []

        def flaky_opener(url):
            attempts.append(url)
            if len(attempts) == 1:
                raise urllib.error.HTTPError(url, 429, "rate limited", {}, None)
            return SEARCH_FIXTURE

        sleeps = []
        retried = Client(raw_dir=tmp / "retry", opener=flaky_opener,
                         sleeper=sleeps.append, clock=lambda: 0.0)
        retried.search("10.5555/source-paper")
        bad += check(len(attempts) == 2 and retried.spent == 1 and 2.0 in sleeps,
                     "429 retry accounting was not bounded")

        failed_attempts = []

        def always_busy(url):
            failed_attempts.append(url)
            raise urllib.error.HTTPError(url, 503, "busy", {}, None)

        try:
            Client(raw_dir=tmp / "failed", opener=always_busy,
                   sleeper=lambda seconds: None).search("10.5555/failing-paper")
            bad += check(False, "retryable failure did not stop")
        except urllib.error.HTTPError:
            pass
        bad += check(len(failed_attempts) == europepmc.MAX_ATTEMPTS,
                     "retry attempts exceeded the configured bound")

        # (e) A non-JSON-object response is rejected.
        try:
            Client(raw_dir=tmp / "list", opener=lambda url: [SEARCH_FIXTURE],
                   sleeper=lambda seconds: None).search("10.5555/source-paper")
            bad += check(False, "a JSON list response was accepted as a Europe PMC object")
        except ValueError:
            pass

        # Identical bytes retain a single raw object but preserve each source
        # observation in the manifest.
        same = Client(raw_dir=tmp / "same", opener=lambda url: SEARCH_FIXTURE,
                      sleeper=lambda seconds: None)
        first = same.search("10.5555/source-paper")
        second = same.search("10.5555/other-paper")
        records = [json.loads(line) for line in manifest.read_text().splitlines()]
        bad += check(first.sha256 == second.sha256 and first.path == second.path
                     and records[-2]["sha256"] == records[-1]["sha256"]
                     and records[-2]["url"] != records[-1]["url"],
                     "duplicate bytes did not deduplicate without losing observations")
    finally:
        europepmc.MANIFEST = real_manifest
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_europepmc:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
