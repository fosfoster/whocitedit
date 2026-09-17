#!/usr/bin/env python3
"""Offline coverage for Europe PMC work-assertion persistence."""
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


def europepmc_search(result_id: str, doi: str, title: str, journal: str,
                      abbrev: str, pub_date: str) -> dict:
    return {
        "version": "6.9",
        "hitCount": 1,
        "request": {"queryString": f'DOI:"{doi}"', "resultType": "core"},
        "resultList": {
            "result": [
                {
                    "id": result_id,
                    "source": "MED",
                    "doi": doi,
                    "title": title,
                    "journalInfo": {
                        "journal": {"title": journal, "medlineAbbreviation": abbrev},
                        "printPublicationDate": pub_date,
                    },
                    "firstPublicationDate": pub_date,
                }
            ]
        },
    }


def europepmc_references(source: str, request_id: str) -> dict:
    return {
        "version": "6.9",
        "hitCount": 1,
        "request": {"id": request_id, "source": source},
        "referenceList": {
            "reference": [
                {
                    "id": "99999999",
                    "source": "MED",
                    "publicationType": "research-article",
                    "authorString": "Example Z.",
                    "title": "A fixture reference that must not become a work assertion",
                    "doi": "10.5555/should-not-appear",
                }
            ]
        },
    }


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
        # Two independent Europe PMC search payloads for the same work: both retained.
        store_payload(
            tmp,
            europepmc_search(
                "38000001", "10.5555/w1", "First Europe PMC Title",
                "Journal One", "J One", "2024-01-15",
            ),
            "file://europepmc-w1-a",
        )
        store_payload(
            tmp,
            europepmc_search(
                "38000002", "10.5555/w1", "Second Europe PMC Title",
                "Journal Two", "J Two", "2024-02-20",
            ),
            "file://europepmc-w1-b",
        )
        # DOI outside the corpus: nothing should be stored for it.
        store_payload(
            tmp,
            europepmc_search(
                "38000003", "10.9999/outside", "Outside Title",
                "Nowhere Journal", "Nwhr J", "2024-03-01",
            ),
            "file://europepmc-outside",
        )
        # A Europe PMC *references* payload must never be mistaken for a search
        # payload and must not produce a work assertion row.
        store_payload(
            tmp,
            europepmc_references("MED", "38000001"),
            "file://europepmc-references",
        )

        derive.RAW = tmp / "raw"
        derive.MANIFEST = tmp / "manifest.jsonl"
        conn = db.connect(tmp / "corpus.db")
        stats = derive.load(conn)

        bad += check(stats["europepmc_assertions"] == 2,
                     "load() did not count the two Europe PMC assertions matched by DOI")

        rows = conn.execute(
            "SELECT raw_sha, title, venue, venue_short, publication_date "
            "FROM europepmc_work_assertion WHERE work_id = 'W1' ORDER BY title"
        ).fetchall()
        bad += check(len(rows) == 2,
                     "both Europe PMC search payloads for the same work were not retained")
        stored = {(r["title"], r["venue"], r["venue_short"], r["publication_date"]) for r in rows}
        bad += check(
            stored == {
                ("First Europe PMC Title", "Journal One", "J One", "2024-01-15"),
                ("Second Europe PMC Title", "Journal Two", "J Two", "2024-02-20"),
            },
            "stored title/venue/venue_short/publication_date did not match the search result fields",
        )
        bad += check(
            len({r["raw_sha"] for r in rows}) == 2,
            "the two rows for the same work were not keyed by distinct raw_sha values",
        )

        outside_count = conn.execute(
            "SELECT COUNT(*) c FROM europepmc_work_assertion WHERE work_id != 'W1'"
        ).fetchone()["c"]
        bad += check(outside_count == 0,
                     "a search result with a DOI outside the corpus stored a row anyway")

        total_count = conn.execute(
            "SELECT COUNT(*) c FROM europepmc_work_assertion"
        ).fetchone()["c"]
        bad += check(total_count == 2,
                     "a references payload produced a europepmc_work_assertion row")

        work_row = conn.execute(
            "SELECT title, type, source_name FROM work WHERE id = 'W1'"
        ).fetchone()
        bad += check(
            work_row["title"] == "Original OpenAlex Title"
            and work_row["type"] == "article"
            and work_row["source_name"] == "Journal of Testing",
            "an OpenAlex work column was overwritten by a Europe PMC payload",
        )
        conn.close()
    finally:
        derive.RAW, derive.MANIFEST = saved_raw, saved_manifest
        shutil.rmtree(tmp, ignore_errors=True)

    if bad:
        print(f"{bad} check(s) failed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
