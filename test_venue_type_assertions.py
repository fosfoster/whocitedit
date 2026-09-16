#!/usr/bin/env python3
"""Offline coverage for Crossref venue/work-type persistence and comparison."""
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import db
import derive


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def store_payload(root: Path, payload, url: str) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sha = hashlib.sha256(body).hexdigest()
    path = root / "raw" / sha[:2] / f"{sha}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    with (root / "manifest.jsonl").open("a") as fh:
        fh.write(json.dumps({
            "sha256": sha,
            "url": url,
            "fetched_at": "2026-09-15T00:00:00+00:00",
            "path": str(path.relative_to(root)),
        }, sort_keys=True) + "\n")
    return sha


def openalex_work(wid: str, doi: str) -> dict:
    return {
        "id": f"https://openalex.org/{wid}",
        "doi": doi,
        "title": "Original OpenAlex Title",
        "publication_year": 2020,
        "publication_date": "2020-01-01",
        "type": "article",
        "cited_by_count": 5,
        "referenced_works": [],
        "primary_location": {
            "source": {"id": "https://openalex.org/S1", "display_name": "Journal of Testing"},
        },
    }


def crossref_envelope(doi: str, container_title, short_container_title, work_type: str) -> dict:
    message = {"DOI": doi, "type": work_type}
    if container_title is not None:
        message["container-title"] = container_title
    if short_container_title is not None:
        message["short-container-title"] = short_container_title
    return {"status": "ok", "message-type": "work", "message": message}


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved_raw, saved_manifest = derive.RAW, derive.MANIFEST
    try:
        store_payload(
            tmp,
            {"results": [openalex_work("W1", "https://doi.org/10.5555/w1")]},
            "file://w1",
        )
        # Two independent Crossref envelopes for the same work: both retained.
        store_payload(
            tmp,
            crossref_envelope("10.5555/w1", ["Journal of Testing"], ["J. Test."], "journal-article"),
            "file://crossref-w1-a",
        )
        store_payload(
            tmp,
            crossref_envelope("10.5555/w1", ["A Different Name"], ["ADN"], "journal-article"),
            "file://crossref-w1-b",
        )
        # DOI outside the corpus: nothing should be stored for it.
        store_payload(
            tmp,
            crossref_envelope("10.9999/outside", ["Nowhere Journal"], None, "journal-article"),
            "file://crossref-outside",
        )

        derive.RAW = tmp / "raw"
        derive.MANIFEST = tmp / "manifest.jsonl"
        conn = db.connect(tmp / "corpus.db")
        stats = derive.load(conn)

        bad += check(stats["crossref_assertions"] == 2,
                     "load() did not count the two Crossref assertions matched by DOI")

        rows = conn.execute(
            "SELECT venue, venue_short, work_type FROM crossref_work_assertion "
            "WHERE work_id = 'W1' ORDER BY venue"
        ).fetchall()
        bad += check(len(rows) == 2,
                     "both Crossref envelopes for the same work were not retained")
        stored = {(r["venue"], r["venue_short"], r["work_type"]) for r in rows}
        bad += check(
            stored == {
                ("Journal of Testing", "J. Test.", "journal-article"),
                ("A Different Name", "ADN", "journal-article"),
            },
            "stored venue/short-venue/type did not match the Crossref message fields",
        )

        outside_count = conn.execute(
            "SELECT COUNT(*) c FROM crossref_work_assertion WHERE work_id != 'W1'"
        ).fetchone()["c"]
        bad += check(outside_count == 0,
                     "an envelope with a DOI outside the corpus stored a row anyway")

        work_row = conn.execute(
            "SELECT title, type, source_name FROM work WHERE id = 'W1'"
        ).fetchone()
        bad += check(
            work_row["title"] == "Original OpenAlex Title"
            and work_row["type"] == "article"
            and work_row["source_name"] == "Journal of Testing",
            "an OpenAlex work column was overwritten by a Crossref payload",
        )
        conn.close()
    finally:
        derive.RAW, derive.MANIFEST = saved_raw, saved_manifest
        shutil.rmtree(tmp, ignore_errors=True)

    # Status helpers, independent of storage.
    bad += check(
        derive.venue_comparison_status("Journal of Testing", "Journal of Testing", None) == "agree",
        "identical venues did not agree",
    )
    bad += check(
        derive.venue_comparison_status("J Test", "Journal of Testing", "J. Test.") == "agree",
        "an abbreviation match against the short container title was not reported as agreement",
    )
    bad += check(
        derive.venue_comparison_status("Journal of Testing", "Completely Different Venue", "CDV") == "disagree",
        "differing venues with no abbreviation match did not disagree",
    )
    bad += check(
        derive.venue_comparison_status(None, "Journal of Testing", None) == "unavailable",
        "a missing OpenAlex venue was not reported as unavailable",
    )
    bad += check(
        derive.venue_comparison_status("Journal of Testing", None, None) == "unavailable",
        "a missing Crossref venue was not reported as unavailable",
    )
    bad += check(
        derive.venue_comparison_status("The Journal", "Journal", None) == "agree",
        "a leading 'the' article difference was reported as a contradiction",
    )

    bad += check(
        derive.work_type_comparison_status("article", "journal-article") == "agree",
        "a mapped, matching work type did not agree",
    )
    bad += check(
        derive.work_type_comparison_status("book-chapter", "journal-article") == "disagree",
        "a mapped, mismatched work type did not disagree",
    )
    bad += check(
        derive.work_type_comparison_status(None, "journal-article") == "unavailable",
        "a missing OpenAlex type was not reported as unavailable",
    )
    bad += check(
        derive.work_type_comparison_status("article", None) == "unavailable",
        "a missing Crossref type was not reported as unavailable",
    )
    bad += check(
        derive.work_type_comparison_status("article", "grant") == "incomparable",
        "an unmapped Crossref type was not reported as incomparable rather than disagree",
    )

    if bad:
        print(f"{bad} check(s) failed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
