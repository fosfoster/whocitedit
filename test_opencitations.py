#!/usr/bin/env python3
"""Fixture-only tests for COCI retention and the operator citation action."""
import json
import shutil
import sys
import tempfile
import urllib.error
from pathlib import Path

import harvest
import opencitations
from opencitations import BudgetExhausted, Client, normalize_doi


ROOT = Path(__file__).parent
FIXTURE = json.loads((ROOT / "docs" / "fixtures" / "opencitations" / "references.json").read_text())


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    manifest = tmp / "manifest.jsonl"
    real_manifest = opencitations.MANIFEST
    real_root = harvest.ROOT
    real_coci_client = harvest.CociClient
    opencitations.MANIFEST = manifest
    try:
        calls = []
        sleeps = []

        def fixture_opener(url):
            calls.append(url)
            return FIXTURE

        c = Client(raw_dir=tmp / "raw", opener=fixture_opener,
                   sleeper=sleeps.append, clock=lambda: 0.0)
        fetched = c.references("https://doi.org/10.5555/source-paper")
        expected_url = f"{opencitations.BASE}/references/10.5555/source-paper"
        bad += check(fetched.url == expected_url, f"DOI URL was {fetched.url}")
        bad += check(calls == [expected_url], "fixture opener did not receive the DOI URL")
        bad += check(c._url("10.5555/source paper")
                     == f"{opencitations.BASE}/references/10.5555/source%20paper",
                     "DOI path characters were not URL-encoded")
        bad += check(fetched.payload == FIXTURE and fetched.payload[0]["cited"] == "10.5555/reference-one",
                     "COCI fixture list was not parsed")
        bad += check(c.spent == opencitations.REQUEST_COST and c.remaining == c.budget - 1,
                     "request charge or remaining budget was wrong")
        bad += check(normalize_doi("doi:10.5555/source-paper") == "10.5555/source-paper",
                     "bare DOI normalization failed")

        # Refusal happens before transport or storage.
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

        # Retryable transport failures consume one request budget, not one per
        # attempt, and retry from the injected fixture transport.
        attempts = []

        def flaky_fixture_opener(url):
            attempts.append(url)
            if len(attempts) == 1:
                raise urllib.error.HTTPError(url, 503, "busy", {}, None)
            return FIXTURE

        retry_sleeps = []
        retried = Client(raw_dir=tmp / "retry", opener=flaky_fixture_opener,
                         sleeper=retry_sleeps.append, clock=lambda: 0.0)
        retried.references("10.5555/source-paper")
        retried.references("10.5555/second-paper")
        bad += check(len(attempts) == 3 and retried.spent == 2,
                     "retry changed request accounting")
        bad += check(2.0 in retry_sleeps, f"retry backoff missing: {retry_sleeps}")
        bad += check(any(delay == 1.0 / opencitations.MAX_REQUESTS_PER_SECOND for delay in retry_sleeps),
                     f"rate throttle missing: {retry_sleeps}")

        # Canonical bytes give duplicate COCI lists one retained raw object,
        # while both observations remain in the manifest.
        same = Client(raw_dir=tmp / "same", opener=lambda url: FIXTURE,
                      sleeper=lambda seconds: None)
        first = same.references("10.5555/source-paper")
        second = same.references("10.5555/other-paper")
        lines = [json.loads(line) for line in manifest.read_text().splitlines()]
        bad += check(first.sha256 == second.sha256 and first.path == second.path,
                     "identical COCI lists were not content-addressed")
        bad += check(first.path.name == f"{first.sha256}.json" and json.loads(first.path.read_text()) == FIXTURE,
                     "retained bytes do not match the fixture")
        bad += check(len(lines) == 5 and lines[-2]["sha256"] == lines[-1]["sha256"]
                     and lines[-2]["url"] != lines[-1]["url"],
                     "manifest did not preserve both COCI observations")
        bad += check(set(first.provenance()) == {"url", "sha256", "fetched_at"},
                     "provenance shape changed")

        # The citation action discovers OpenAlex DOIs and ignores the COCI list
        # sharing its raw directory, so author discovery keeps working later.
        harvest.ROOT = tmp / "operator"
        raw = harvest.ROOT / "harvest" / "raw"
        raw.mkdir(parents=True)
        (raw / "works.json").write_text(json.dumps({"results": [
            {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.5555/source-paper",
             "authorships": [{"author": {"id": "https://openalex.org/A1"}}]},
            {"id": "https://openalex.org/W2", "doi": "10.5555/second-paper", "authorships": []},
            {"id": "https://openalex.org/W3", "doi": None, "authorships": []},
        ]}))
        (raw / "coci.json").write_text(json.dumps(FIXTURE))
        harvested = []

        class RecordingCoci:
            def __init__(self):
                self.spent = 0

            @property
            def remaining(self):
                return 10_000 - self.spent

            def references(self, doi):
                harvested.append(doi)
                self.spent += 1

        bad += check(harvest.dois_in_raw() == ["10.5555/second-paper", "10.5555/source-paper"],
                     "operator DOI discovery missed or duplicated works")
        bad += check(harvest.harvest_citations(RecordingCoci()) == 2
                     and harvested == ["10.5555/second-paper", "10.5555/source-paper"],
                     "operator citation action did not fetch discovered DOIs")
        bad += check(harvest.author_ids_in_raw() == ["A1"],
                     "a stored COCI list broke OpenAlex author discovery")

        # Exercise the operator-only command routing without constructing a
        # live transport. `all` deliberately remains the OpenAlex refresh.
        harvested.clear()
        harvest.CociClient = RecordingCoci
        bad += check(harvest.main(["harvest.py", "citations"]) == 0
                     and harvested == ["10.5555/second-paper", "10.5555/source-paper"],
                     "harvest.py citations did not dispatch the COCI action")
    finally:
        opencitations.MANIFEST = real_manifest
        harvest.ROOT = real_root
        harvest.CociClient = real_coci_client
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_opencitations:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
