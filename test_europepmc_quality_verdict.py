#!/usr/bin/env python3
"""derive.score_quality() must fold Europe PMC's venue assertion into the
three-way source verdict quality.assess() reports, alongside Crossref's.

Covers the wiring end to end through a fixture corpus: an Europe-PMC-only
disagreement must name `europepmc_disagrees`, the mirror Crossref-only
disagreement must name `crossref_disagrees`, three sources agreeing must not
weaken the band, and a work with no Europe PMC assertion at all must land on
exactly the evidence direction it produced before Europe PMC was wired in
(a crossref-only two-way comparison).
"""
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import db
import derive
import quality as Q


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
            "fetched_at": "2026-09-20T00:00:00+00:00",
            "path": str(path.relative_to(root)),
        }, sort_keys=True) + "\n")
    return sha


TITLE = "A Sound Record About Testing"
DATE = "2020-01-01"


def openalex_work(wid: str, doi: str, venue: str) -> dict:
    return {
        "id": f"https://openalex.org/{wid}",
        "doi": doi,
        "title": TITLE,
        "publication_year": 2020,
        "publication_date": DATE,
        "type": "article",
        "cited_by_count": 5,
        "referenced_works": ["https://openalex.org/W999"],
        "authorships": [
            {
                "author_position": "first",
                "author": {"id": "https://openalex.org/A1", "display_name": "A. One"},
            },
        ],
        "primary_location": {
            "source": {"id": "https://openalex.org/S1", "display_name": venue},
        },
    }


def crossref_envelope(doi: str, venue: str) -> dict:
    return {
        "status": "ok",
        "message-type": "work",
        "message": {
            "DOI": doi,
            "type": "journal-article",
            "title": [TITLE],
            "container-title": [venue],
            "issued": {"date-parts": [[2020, 1, 1]]},
        },
    }


def europepmc_search(result_id: str, doi: str, venue: str) -> dict:
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
                    "title": TITLE,
                    "journalInfo": {
                        "journal": {"title": venue, "medlineAbbreviation": venue},
                        "printPublicationDate": DATE,
                    },
                    "firstPublicationDate": DATE,
                }
            ]
        },
    }


AGREED_VENUE = "Journal of Testing"
DISAGREED_VENUE = "A Totally Different Venue"

# W1: Europe PMC disagrees on venue, Crossref agrees -> europepmc_disagrees.
# W2: mirror -- Crossref disagrees, Europe PMC agrees -> crossref_disagrees.
# W3: OpenAlex, Crossref and Europe PMC all agree -> no weakening from this signal.
# W4: no Europe PMC assertion at all -> unaffected, crossref-only two-way result.
WORKS = {
    "W1": "10.5555/w1",
    "W2": "10.5555/w2",
    "W3": "10.5555/w3",
    "W4": "10.5555/w4",
}


def stage(tmp: Path) -> None:
    for wid, doi in WORKS.items():
        store_payload(
            tmp,
            {"results": [openalex_work(wid, f"https://doi.org/{doi}", AGREED_VENUE)]},
            f"file://openalex-{wid}",
        )

    store_payload(tmp, crossref_envelope(WORKS["W1"], AGREED_VENUE), "file://crossref-w1")
    store_payload(tmp, europepmc_search("38000001", WORKS["W1"], DISAGREED_VENUE), "file://europepmc-w1")

    store_payload(tmp, crossref_envelope(WORKS["W2"], DISAGREED_VENUE), "file://crossref-w2")
    store_payload(tmp, europepmc_search("38000002", WORKS["W2"], AGREED_VENUE), "file://europepmc-w2")

    store_payload(tmp, crossref_envelope(WORKS["W3"], AGREED_VENUE), "file://crossref-w3")
    store_payload(tmp, europepmc_search("38000003", WORKS["W3"], AGREED_VENUE), "file://europepmc-w3")

    store_payload(tmp, crossref_envelope(WORKS["W4"], AGREED_VENUE), "file://crossref-w4")


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved_raw, saved_manifest = derive.RAW, derive.MANIFEST
    try:
        stage(tmp)
        derive.RAW = tmp / "raw"
        derive.MANIFEST = tmp / "manifest.jsonl"

        conn = db.connect(tmp / "corpus.db")
        derive.load(conn)
        derive.score_quality(conn)

        def evidence_for(wid: str) -> tuple[str, dict]:
            row = conn.execute(
                "SELECT quality, quality_evidence FROM work WHERE id = ?", (wid,)
            ).fetchone()
            evidence = Q.decode_evidence(row["quality_evidence"])
            return row["quality"], {e["signal"]: e for e in evidence}

        # -- W1: Europe PMC disagrees, Crossref agrees ------------------------
        band, by_signal = evidence_for("W1")
        venue = by_signal["venue_source"]
        bad += check(venue.get("verdict") == Q.EUROPEPMC_DISAGREES,
                     f"W1 venue_source verdict {venue.get('verdict')!r}, expected europepmc_disagrees")
        bad += check(venue["direction"] == "weakens", "W1 venue_source did not weaken despite europepmc_disagrees")
        bad += check(band in (Q.PARTIAL, Q.SUSPECT), f"W1 band {band!r} was not weakened")

        # -- W2: mirror -- Crossref disagrees, Europe PMC agrees --------------
        band, by_signal = evidence_for("W2")
        venue = by_signal["venue_source"]
        bad += check(venue.get("verdict") == Q.CROSSREF_DISAGREES,
                     f"W2 venue_source verdict {venue.get('verdict')!r}, expected crossref_disagrees")
        bad += check(venue["direction"] == "weakens", "W2 venue_source did not weaken despite crossref_disagrees")
        bad += check(band in (Q.PARTIAL, Q.SUSPECT), f"W2 band {band!r} was not weakened")

        # -- W3: all three sources agree ---------------------------------------
        band, by_signal = evidence_for("W3")
        venue = by_signal["venue_source"]
        bad += check(venue.get("verdict") == Q.AGREE, f"W3 venue_source verdict {venue.get('verdict')!r}, expected agree")
        bad += check(venue["direction"] == "supports", "W3 venue_source did not support despite three-way agreement")
        bad += check(band == Q.COMPLETE, f"W3 band {band!r}, expected complete with no weakening from source signals")

        # -- W4: no Europe PMC assertion at all --------------------------------
        # Must land on exactly the verdict/direction Crossref-only comparison
        # produced before Europe PMC was wired into score_quality: `agree`
        # (from Crossref alone), `supports`, unaffected by the missing Europe
        # PMC row.
        band, by_signal = evidence_for("W4")
        venue = by_signal["venue_source"]
        bad += check(venue.get("verdict") == Q.AGREE,
                     f"W4 (no Europe PMC assertion) venue_source verdict {venue.get('verdict')!r}, expected agree")
        bad += check(venue["direction"] == "supports",
                     "W4 (no Europe PMC assertion) venue_source direction changed from pre-Europe-PMC behavior")
        bad += check(band == Q.COMPLETE, f"W4 band {band!r}, expected complete (unchanged by the missing assertion)")

        conn.close()
    finally:
        derive.RAW, derive.MANIFEST = saved_raw, saved_manifest
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_europepmc_quality_verdict:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
