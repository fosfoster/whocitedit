#!/usr/bin/env python3
"""Fixture-only tests for Crossref retention and its operator harvest action."""
import hashlib
import json
import shutil
import sys
import tempfile
import urllib.error
from pathlib import Path

import crossref
import harvest
from crossref import BudgetExhausted, Client, normalize_doi


ROOT = Path(__file__).parent
FIXTURE = json.loads((ROOT / "docs" / "fixtures" / "crossref" / "work.json").read_text())


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
    real_root = harvest.ROOT
    real_crossref_client = harvest.CrossrefClient
    real_openalex_client = harvest.Client
    crossref.MANIFEST = manifest
    try:
        calls = []

        def fixture_opener(url):
            calls.append(url)
            return FIXTURE

        c = Client(mailto="t@example.com", raw_dir=tmp / "raw", opener=fixture_opener,
                   sleeper=lambda seconds: None, clock=lambda: 0.0)
        fetched = c.work("https://doi.org/10.5555/source-paper")
        expected_url = f"{crossref.BASE}/10.5555%2Fsource-paper?mailto=t%40example.com"
        bad += check(fetched.url == expected_url and calls == [expected_url],
                     "DOI was not safely encoded into the Crossref work request")
        bad += check(c._url("doi:10.5555/source paper?query")
                     == f"{crossref.BASE}/10.5555%2Fsource%20paper%3Fquery?mailto=t%40example.com",
                     "DOI punctuation escaped the Crossref path parameter")
        bad += check(normalize_doi("doi:10.5555/source-paper") == "10.5555/source-paper",
                     "DOI normalization failed")

        # Storage is complete before the returned object names it: canonical
        # bytes, their exact SHA-256 filename, and full manifest provenance.
        expected_sha = hashlib.sha256(
            json.dumps(FIXTURE, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        record = json.loads(manifest.read_text().strip())
        bad += check(fetched.payload == FIXTURE and fetched.sha256 == expected_sha
                     and fetched.path.name == f"{expected_sha}.json"
                     and json.loads(fetched.path.read_text()) == FIXTURE,
                     "Crossref response was not retained under its canonical hash")
        bad += check(record["url"] == expected_url and record["sha256"] == expected_sha
                     and record["path"] == str(fetched.path) and record["fetched_at"]
                     and set(record) == {"url", "sha256", "path", "fetched_at"},
                     "manifest lost Crossref observation provenance")

        # Refusal occurs before transport, so a bounded run cannot make one
        # request beyond its declared allowance.
        refused = []
        small = Client(raw_dir=tmp / "small", budget=0,
                       opener=lambda url: refused.append(url) or FIXTURE,
                       sleeper=lambda seconds: None)
        try:
            small.work("10.5555/source-paper")
            bad += check(False, "a request was allowed with no remaining budget")
        except BudgetExhausted:
            pass
        bad += check(small.spent == 0 and not refused, "budget refusal charged or transported")

        # Retries are bounded and charged once per logical request. A second
        # request at a fixed clock also proves the rate throttle is bounded.
        attempts = []

        def flaky_opener(url):
            attempts.append(url)
            if len(attempts) == 1:
                raise urllib.error.HTTPError(url, 503, "busy", {}, None)
            return FIXTURE

        sleeps = []
        retried = Client(raw_dir=tmp / "retry", opener=flaky_opener,
                         sleeper=sleeps.append, clock=lambda: 0.0)
        retried.work("10.5555/source-paper")
        retried.work("10.5555/second-paper")
        bad += check(len(attempts) == 3 and retried.spent == 2 and 2.0 in sleeps
                     and 1.0 / crossref.MAX_REQUESTS_PER_SECOND in sleeps,
                     "retry or throttle accounting was not bounded")

        failed_attempts = []

        def always_busy(url):
            failed_attempts.append(url)
            raise urllib.error.HTTPError(url, 503, "busy", {}, None)

        try:
            Client(raw_dir=tmp / "failed", opener=always_busy,
                   sleeper=lambda seconds: None).work("10.5555/failing-paper")
            bad += check(False, "retryable failure did not stop")
        except urllib.error.HTTPError:
            pass
        bad += check(len(failed_attempts) == crossref.MAX_ATTEMPTS,
                     "retry attempts exceeded the configured bound")

        # Identical bytes retain a single raw object but preserve each source
        # observation in the manifest.
        same = Client(raw_dir=tmp / "same", opener=lambda url: FIXTURE,
                      sleeper=lambda seconds: None)
        first = same.work("10.5555/source-paper")
        second = same.work("10.5555/other-paper")
        records = [json.loads(line) for line in manifest.read_text().splitlines()]
        bad += check(first.sha256 == second.sha256 and first.path == second.path
                     and records[-2]["sha256"] == records[-1]["sha256"]
                     and records[-2]["url"] != records[-1]["url"],
                     "duplicate bytes did not deduplicate without losing observations")

        # Only OpenAlex work pages participate in discovery. Crossref response
        # objects, COCI lists, and OpenAlex author pages share the raw store but
        # cannot create a work DOI visit.
        harvest.ROOT = tmp / "operator"
        raw = harvest.ROOT / "harvest" / "raw"
        raw.mkdir(parents=True)
        (raw / "works.json").write_text(json.dumps({"results": [
            {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.5555/source-paper",
             "authorships": []},
            {"id": "https://openalex.org/W2", "doi": "doi:10.5555/source-paper",
             "authorships": []},
            {"id": "https://openalex.org/W3", "doi": "10.5555/second-paper",
             "authorships": []},
        ]}))
        (raw / "crossref.json").write_text(json.dumps(FIXTURE))
        (raw / "coci.json").write_text(json.dumps([{"citing": "10.5555/not-a-work"}]))
        (raw / "authors.json").write_text(json.dumps({"results": [
            {"doi": "10.5555/not-a-work"}
        ]}))
        harvested = []

        class RecordingCrossref:
            def __init__(self):
                self.spent = 0

            @property
            def remaining(self):
                return 10_000 - self.spent

            def work(self, doi):
                harvested.append(doi)
                self.spent += 1

        expected_dois = ["10.5555/second-paper", "10.5555/source-paper"]
        bad += check(harvest.dois_in_raw(normalize_doi) == expected_dois,
                     "stored OpenAlex work DOI discovery was not unique")
        bad += check(harvest.harvest_crossref(RecordingCrossref()) == 2
                     and harvested == expected_dois,
                     "Crossref harvest did not visit each normalized DOI once")

        # `crossref` is an explicit operator action; `all` remains OpenAlex
        # only and must never construct the Crossref transport.
        harvested.clear()
        harvest.CrossrefClient = RecordingCrossref
        bad += check(harvest.main(["harvest.py", "crossref"]) == 0
                     and harvested == expected_dois,
                     "harvest.py crossref did not dispatch the operator action")

        class NoCrossref:
            def __init__(self):
                raise AssertionError("all must not create a Crossref client")

        class EmptyOpenAlex:
            mailto = ""
            spent = 0
            remaining = 100_000

            def paginate(self, *args, **kwargs):
                return iter(())

            def page(self, *args, **kwargs):
                raise AssertionError("no authors should be discovered")

        harvest.CrossrefClient = NoCrossref
        harvest.Client = EmptyOpenAlex
        bad += check(harvest.main(["harvest.py", "all"]) == 0,
                     "all no longer remains the OpenAlex refresh")
    finally:
        crossref.MANIFEST = real_manifest
        harvest.ROOT = real_root
        harvest.CrossrefClient = real_crossref_client
        harvest.Client = real_openalex_client
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_crossref:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
