#!/usr/bin/env python3
"""The client. Credits are metered rather than counted, and the raw store is what
every provenance claim on the site rests on, so both get real tests."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import openalex
from openalex import BudgetExhausted, Client, short_id


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    manifest = tmp / "manifest.jsonl"
    real_manifest = openalex.MANIFEST
    openalex.MANIFEST = manifest
    try:
        pages = [
            {"results": [{"id": f"https://openalex.org/W{i}"} for i in range(2)],
             "meta": {"next_cursor": "c2"}},
            {"results": [{"id": "https://openalex.org/W9"}], "meta": {"next_cursor": None}},
        ]
        calls = []

        def opener(url):
            calls.append(url)
            return pages[min(len(calls) - 1, len(pages) - 1)]

        c = Client(mailto="t@example.com", raw_dir=tmp / "raw", opener=opener, sleeper=lambda s: None)

        # A list request costs ten times a singleton one. A harvester that
        # counted requests instead of credits would overrun by 10x.
        c.singleton("works/W1")
        bad += check(c.spent == openalex.CREDITS_SINGLETON, f"singleton charged {c.spent}")
        c.page("works")
        bad += check(c.spent == openalex.CREDITS_SINGLETON + openalex.CREDITS_LIST,
                     f"list charged {c.spent - 1}")

        # The polite-pool contact goes on every request.
        bad += check(all("mailto=t%40example.com" in u for u in calls), "mailto missing")

        # Refuse rather than overrun.
        small = Client(raw_dir=tmp / "raw2", budget=5, opener=opener, sleeper=lambda s: None)
        try:
            small.page("works")
            bad += check(False, "a 10-credit call was allowed against a 5-credit budget")
        except BudgetExhausted:
            pass
        bad += check(small.spent == 0, "a refused call still charged")

        # Paging follows the cursor and stops when the cursor runs out.
        calls.clear()
        c2 = Client(raw_dir=tmp / "raw3", opener=opener, sleeper=lambda s: None)
        got = list(c2.paginate("works"))
        bad += check(len(got) == 2, f"paginate yielded {len(got)} pages")
        bad += check("cursor=c2" in calls[1], f"second call did not use the cursor: {calls[1]}")

        # max_records stops early, which is what bounds the corpus.
        calls.clear()
        c3 = Client(raw_dir=tmp / "raw4", opener=opener, sleeper=lambda s: None)
        bad += check(len(list(c3.paginate("works", max_records=1))) == 1, "max_records ignored")

        # The raw store is content-addressed: identical bytes are one file, and
        # the filename IS the hash the site cites.
        c4 = Client(raw_dir=tmp / "raw5", opener=lambda u: {"results": [{"id": "x"}]},
                    sleeper=lambda s: None)
        f1 = c4.singleton("a")
        f2 = c4.singleton("b")
        bad += check(f1.sha256 == f2.sha256, "same payload hashed differently")
        bad += check(f1.path.exists() and f1.path.name.startswith(f1.sha256[:8]),
                     "raw file not named by its hash")
        stored = json.loads(f1.path.read_text())
        bad += check(stored == f1.payload, "stored bytes differ from the parsed payload")
        bad += check(set(f1.provenance()) == {"url", "sha256", "fetched_at"}, "provenance shape")

        # Two fetches of the same bytes still record two manifest lines: the
        # payload is the same file, but when and from where we saw it is not.
        lines = [json.loads(l) for l in manifest.read_text().strip().splitlines()]
        tail = lines[-2:]
        bad += check(len(lines) == 7, f"manifest recorded {len(lines)} of 7 fetches")
        bad += check(tail[0]["sha256"] == tail[1]["sha256"], "identical payloads hashed differently")
        bad += check(tail[0]["url"] != tail[1]["url"], "the two fetch URLs were not both recorded")

        bad += check(short_id("https://openalex.org/W123") == "W123", "short_id")
        bad += check(short_id("https://openalex.org/A5/") == "A5", "short_id trailing slash")
        bad += check(short_id(None) is None, "short_id None")
    finally:
        openalex.MANIFEST = real_manifest
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_openalex:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
