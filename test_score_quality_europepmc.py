#!/usr/bin/env python3
"""score_quality() must fold Europe PMC title/date assertions into the verdict.

Regression for wiring europepmc_work_assertion into derive.score_quality():
before that wiring, a Europe-PMC-only title or date disagreement was invisible
to quality.assess() (only venue_status/work_type_status were passed), so a
work like this scored COMPLETE with no europepmc_disagrees verdict anywhere in
its evidence. This must fail against that behaviour.
"""
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import db
import derive
import quality


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
        "referenced_works": ["https://openalex.org/W999"],
        "authorships": [
            {"author_position": "first", "author": {"id": "https://openalex.org/A1", "display_name": "A. One"}},
        ],
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
        # Europe PMC asserts a different title and a different publication date
        # for the same DOI; OpenAlex's own venue matches so venue is not the
        # signal under test.
        store_payload(
            tmp,
            europepmc_search(
                "38000001", "10.5555/w1", "A Completely Different Title",
                "Journal of Testing", "J. Test.", "2021-06-01",
            ),
            "file://europepmc-w1",
        )

        derive.RAW = tmp / "raw"
        derive.MANIFEST = tmp / "manifest.jsonl"
        conn = db.connect(tmp / "corpus.db")
        derive.load(conn)
        derive.score_quality(conn)

        row = conn.execute(
            "SELECT quality, quality_evidence FROM work WHERE id = 'W1'"
        ).fetchone()
        bad += check(
            row["quality"] in (quality.PARTIAL, quality.SUSPECT),
            f"a Europe-PMC-only title/date disagreement did not score PARTIAL/SUSPECT (got {row['quality']!r})",
        )

        evidence = quality.decode_evidence(row["quality_evidence"])
        verdicts = {e["signal"]: e.get("verdict") for e in evidence if "verdict" in e}
        bad += check(
            verdicts.get("title_source") == quality.EUROPEPMC_DISAGREES,
            f"title_source evidence did not carry europepmc_disagrees (got {verdicts.get('title_source')!r})",
        )
        bad += check(
            verdicts.get("date_source") == quality.EUROPEPMC_DISAGREES,
            f"date_source evidence did not carry europepmc_disagrees (got {verdicts.get('date_source')!r})",
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
