#!/usr/bin/env python3
"""Fixture-only tests for Semantic Scholar retention and reference extraction."""
import hashlib
import json
import shutil
import sys
import tempfile
import urllib.error
from pathlib import Path

import semanticscholar
from semanticscholar import BudgetExhausted, Client, normalize_doi, reference_dois


ROOT = Path(__file__).parent
FIXTURE = json.loads(
    (ROOT / "docs" / "fixtures" / "semanticscholar" / "references.json").read_text()
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
    real_manifest = semanticscholar.MANIFEST
    semanticscholar.MANIFEST = manifest
    try:
        bad += check(normalize_doi("doi:10.5555/source-paper") == "10.5555/source-paper",
                     "DOI normalization failed")
        bad += check(normalize_doi("https://doi.org/10.5555/source-paper")
                     == "10.5555/source-paper",
                     "resolver URL DOI was not normalized")
        try:
            normalize_doi("not-a-doi")
            bad += check(False, "an invalid DOI was accepted")
        except ValueError:
            pass

        calls = []

        def fixture_opener(url):
            calls.append(url)
            return FIXTURE

        c = Client(raw_dir=tmp / "raw", opener=fixture_opener,
                   sleeper=lambda seconds: None, clock=lambda: 0.0)
        fetched = c.references("https://doi.org/10.5555/source-paper")
        expected_url = (
            f"{semanticscholar.BASE}/DOI%3A10.5555%2Fsource-paper"
            "?fields=externalIds,references.externalIds"
        )
        bad += check(fetched.url == expected_url and calls == [expected_url],
                     "DOI was not safely encoded into the Semantic Scholar request")
        bad += check(c._url("doi:10.5555/source paper")
                     == f"{semanticscholar.BASE}/DOI%3A10.5555%2Fsource%20paper"
                        "?fields=externalIds,references.externalIds",
                     "DOI punctuation escaped the Semantic Scholar path parameter")

        # Storage is complete before the returned object names it: canonical
        # bytes, their exact SHA-256 filename, and full manifest provenance.
        expected_sha = hashlib.sha256(
            json.dumps(FIXTURE, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        record = json.loads(manifest.read_text().strip())
        bad += check(fetched.payload == FIXTURE and fetched.sha256 == expected_sha
                     and fetched.path.name == f"{expected_sha}.json"
                     and json.loads(fetched.path.read_text()) == FIXTURE,
                     "Semantic Scholar response was not retained under its canonical hash")
        bad += check(fetched.provenance() == {"url": expected_url, "sha256": expected_sha,
                                               "fetched_at": fetched.fetched_at},
                     "provenance() dropped a required field")
        bad += check(record["url"] == expected_url and record["sha256"] == expected_sha
                     and record["path"] == str(fetched.path) and record["fetched_at"]
                     and set(record) == {"url", "sha256", "path", "fetched_at"},
                     "manifest lost Semantic Scholar observation provenance")

        # Refusal occurs before transport, so a bounded run cannot make one
        # request beyond its declared allowance.
        refused = []
        small = Client(raw_dir=tmp / "small", budget=0,
                       opener=lambda url: refused.append(url) or FIXTURE,
                       sleeper=lambda seconds: None)
        try:
            small.references("10.5555/source-paper")
            bad += check(False, "a request was allowed with no remaining budget")
        except BudgetExhausted:
            pass
        bad += check(small.spent == 0 and not refused, "budget refusal charged or transported")

        # Retries are bounded and charged once per logical request; a second
        # request at a fixed clock also proves the rate throttle is bounded.
        attempts = []

        def flaky_opener(url):
            attempts.append(url)
            if len(attempts) == 1:
                raise urllib.error.HTTPError(url, 429, "rate limited", {}, None)
            return FIXTURE

        sleeps = []
        retried = Client(raw_dir=tmp / "retry", opener=flaky_opener,
                          sleeper=sleeps.append, clock=lambda: 0.0)
        retried.references("10.5555/source-paper")
        retried.references("10.5555/second-paper")
        bad += check(len(attempts) == 3 and retried.spent == 2 and 2.0 in sleeps
                     and 1.0 / semanticscholar.MAX_REQUESTS_PER_SECOND in sleeps,
                     "retry or throttle accounting was not bounded")

        failed_attempts = []

        def always_busy(url):
            failed_attempts.append(url)
            raise urllib.error.HTTPError(url, 503, "busy", {}, None)

        try:
            Client(raw_dir=tmp / "failed", opener=always_busy,
                   sleeper=lambda seconds: None).references("10.5555/failing-paper")
            bad += check(False, "retryable failure did not stop")
        except urllib.error.HTTPError:
            pass
        bad += check(len(failed_attempts) == semanticscholar.MAX_ATTEMPTS,
                     "retry attempts exceeded the configured bound")

        # A non-retryable client error is not retried.
        client_errors = []

        def bad_request(url):
            client_errors.append(url)
            raise urllib.error.HTTPError(url, 404, "not found", {}, None)

        try:
            Client(raw_dir=tmp / "notfound", opener=bad_request,
                   sleeper=lambda seconds: None).references("10.5555/missing-paper")
            bad += check(False, "a non-retryable HTTP error was retried away")
        except urllib.error.HTTPError:
            pass
        bad += check(len(client_errors) == 1, "a 404 was retried instead of raised immediately")

        # Identical bytes retain a single raw object but preserve each source
        # observation in the manifest.
        same = Client(raw_dir=tmp / "same", opener=lambda url: FIXTURE,
                      sleeper=lambda seconds: None)
        first = same.references("10.5555/source-paper")
        second = same.references("10.5555/other-paper")
        records = [json.loads(line) for line in manifest.read_text().splitlines()]
        bad += check(first.sha256 == second.sha256 and first.path == second.path
                     and records[-2]["sha256"] == records[-1]["sha256"]
                     and records[-2]["url"] != records[-1]["url"],
                     "duplicate bytes did not deduplicate without losing observations")

        # reference_dois over the committed fixture: two in-corpus references,
        # a no-DOI entry skipped, a resolver-URL duplicate collapsed, the
        # self-pair kept as a raw assertion (derive.py drops self-pairs, not
        # this helper), and an out-of-corpus DOI still surfaced verbatim.
        bad += check(
            reference_dois(FIXTURE) == [
                "10.5555/reference-one",
                "10.5555/reference-two",
                "10.5555/source-paper",
                "10.5555/does-not-exist",
            ],
            "reference_dois did not extract the fixture's reference DOIs correctly",
        )
        bad += check(reference_dois({"references": [
            {"externalIds": {"DOI": "not-a-doi"}},
            {"externalIds": {"DOI": "10.5555/reference-one"}},
            {"externalIds": {"DOI": "10.5555/reference-one"}},
            {"externalIds": {}},
            {},
        ]}) == ["10.5555/reference-one"],
                     "reference_dois did not skip invalid/missing DOIs or dedupe")
    finally:
        semanticscholar.MANIFEST = real_manifest
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_semanticscholar:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
