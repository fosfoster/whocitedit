#!/usr/bin/env python3
"""Fixture-only tests for arXiv retention, Atom parsing, and request construction."""
import hashlib
import json
import shutil
import sys
import tempfile
import urllib.error
from pathlib import Path

import arxiv
from arxiv import BudgetExhausted, Client, normalize_arxiv_id, parse_feed, reference_dois


ROOT = Path(__file__).parent
FIXTURE = json.loads((ROOT / "docs" / "fixtures" / "arxiv" / "query.json").read_text())

ATOM_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>A fixture arXiv paper</title>
    <arxiv:doi>10.5555/source-paper</arxiv:doi>
    <arxiv:reference arxiv:doi="10.5555/reference-one"/>
  </entry>
</feed>
"""


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    manifest = tmp / "manifest.jsonl"
    real_manifest = arxiv.MANIFEST
    arxiv.MANIFEST = manifest
    try:
        # (a) parse_feed turns a small Atom response into the committed
        # fixture's parsed-dict shape.
        bad += check(parse_feed(ATOM_FIXTURE) == FIXTURE,
                     "parse_feed did not round-trip to the committed fixture shape")

        calls = []

        def fixture_opener(url):
            calls.append(url)
            return FIXTURE

        c = Client(raw_dir=tmp / "raw", opener=fixture_opener,
                   sleeper=lambda seconds: None, clock=lambda: 0.0)

        # (b) An arXiv id is safely encoded into the query request.
        fetched = c.query("arXiv:2401.00001v1")
        expected_url = f"{arxiv.BASE}?id_list=2401.00001"
        bad += check(fetched.url == expected_url and calls == [expected_url],
                     "arXiv id was not safely encoded into the query request")

        # A DOI query builds a search_query instead.
        doi_url = c._query_url("10.5555/source paper")
        bad += check(doi_url == f"{arxiv.BASE}?search_query=doi%3A%2210.5555%2Fsource+paper%22",
                     "DOI query was not safely urlencoded")

        # (c) The response is stored under its exact canonical SHA-256 with a
        # complete manifest record and full provenance.
        expected_sha = hashlib.sha256(
            json.dumps(FIXTURE, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        record = json.loads(manifest.read_text().strip())
        bad += check(fetched.payload == FIXTURE and fetched.sha256 == expected_sha
                     and fetched.path.name == f"{expected_sha}.json"
                     and json.loads(fetched.path.read_text()) == FIXTURE,
                     "arXiv response was not retained under its canonical hash")
        bad += check(fetched.provenance() == {"url": expected_url, "sha256": expected_sha,
                                               "fetched_at": fetched.fetched_at},
                     "provenance() dropped a required field")
        bad += check(record["url"] == expected_url and record["sha256"] == expected_sha
                     and record["path"] == str(fetched.path) and record["fetched_at"]
                     and set(record) == {"url", "sha256", "path", "fetched_at"},
                     "manifest lost arXiv observation provenance")

        # (d) A zero-budget client raises BudgetExhausted before the opener
        # is called.
        refused = []
        small = Client(raw_dir=tmp / "small", budget=0,
                       opener=lambda url: refused.append(url) or FIXTURE,
                       sleeper=lambda seconds: None)
        try:
            small.query("2401.00001")
            bad += check(False, "a request was allowed with no remaining budget")
        except BudgetExhausted:
            pass
        bad += check(small.spent == 0 and not refused, "budget refusal charged or transported")

        # (e) Throttling sleeps between calls using the injected clock, honoring
        # arXiv's one-request-per-three-seconds terms.
        clock_time = [0.0]
        sleeps = []
        throttled = Client(raw_dir=tmp / "throttle", opener=fixture_opener,
                            sleeper=sleeps.append, clock=lambda: clock_time[0])
        throttled.query("2401.00001")
        clock_time[0] = 1.0
        throttled.query("2401.00002")
        bad += check(sleeps == [2.0],
                     "throttle did not sleep the remaining time between calls")
        bad += check(arxiv.MAX_REQUESTS_PER_SECOND == 1 / 3.0,
                     "MAX_REQUESTS_PER_SECOND does not honor arXiv's one-request-per-3s terms")

        # (f) A 429 then success is retried.
        attempts = []

        def flaky_opener(url):
            attempts.append(url)
            if len(attempts) == 1:
                raise urllib.error.HTTPError(url, 429, "rate limited", {}, None)
            return FIXTURE

        retry_sleeps = []
        retried = Client(raw_dir=tmp / "retry", opener=flaky_opener,
                          sleeper=retry_sleeps.append, clock=lambda: 0.0)
        retried.query("2401.00001")
        bad += check(len(attempts) == 2 and retried.spent == 1 and 2.0 in retry_sleeps,
                     "429 retry accounting was not bounded")

        # (g) Identical bytes retain a single raw object but preserve each
        # source observation in the manifest.
        same = Client(raw_dir=tmp / "same", opener=lambda url: FIXTURE,
                      sleeper=lambda seconds: None)
        first = same.query("2401.00001")
        second = same.query("2401.00002")
        records = [json.loads(line) for line in manifest.read_text().splitlines()]
        bad += check(first.sha256 == second.sha256 and first.path == second.path
                     and records[-2]["sha256"] == records[-1]["sha256"]
                     and records[-2]["url"] != records[-1]["url"],
                     "duplicate bytes did not deduplicate without losing observations")

        # (h) normalize_arxiv_id handles a bare id, an arXiv: prefix, abs/pdf
        # URLs, and a version suffix.
        bad += check(normalize_arxiv_id("2401.00001") == "2401.00001",
                     "bare arXiv id was altered")
        bad += check(normalize_arxiv_id("arXiv:2401.00001") == "2401.00001",
                     "arXiv: prefix was not stripped")
        bad += check(normalize_arxiv_id("http://arxiv.org/abs/2401.00001v2") == "2401.00001",
                     "abs URL was not normalized")
        bad += check(normalize_arxiv_id("https://arxiv.org/pdf/2401.00001v1.pdf") == "2401.00001",
                     "pdf URL was not normalized")
        bad += check(normalize_arxiv_id("2401.00001v3") == "2401.00001",
                     "version suffix was not stripped")
        try:
            normalize_arxiv_id("")
            bad += check(False, "an empty arXiv id was accepted")
        except ValueError:
            pass

        # (i) reference_dois on the committed fixture returns the DOI that
        # docs/fixtures/openalex/citation-sources.json also asserts, so t2
        # can join across sources.
        bad += check(reference_dois(FIXTURE) == ["10.5555/reference-one"],
                     "reference_dois did not extract the fixture's reference DOI")
        bad += check(reference_dois({"feed": {"entry": [
            {"references": [{"doi": "not-a-doi"}, {"doi": "10.5555/reference-one"},
                             {"doi": "10.5555/reference-one"}, {}]}]}}) ==
                     ["10.5555/reference-one"],
                     "reference_dois did not skip invalid DOIs or dedupe")
    finally:
        arxiv.MANIFEST = real_manifest
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_arxiv:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
