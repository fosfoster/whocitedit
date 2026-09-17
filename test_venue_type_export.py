#!/usr/bin/env python3
"""Venue/work-type source comparison: export shape, quality weakening, score_quality wiring.

Depends on t1's `crossref_work_assertion` table and `derive.venue_comparison_status`
/ `derive.work_type_comparison_status` helpers (see test_venue_type_assertions.py).
This covers the layer built on top of them: the `source_comparison` export block,
the two new `quality.assess()` signals, and `derive.score_quality()` threading the
per-work statuses through.
"""
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import db
import derive
import export_json
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
            "fetched_at": "2026-09-17T00:00:00+00:00",
            "path": str(path.relative_to(root)),
        }, sort_keys=True) + "\n")
    return sha


def openalex_work(wid: str, doi: str, venue: str, work_type: str) -> dict:
    return {
        "id": f"https://openalex.org/{wid}",
        "doi": doi,
        "title": f"Title for {wid}",
        "publication_year": 2020,
        "publication_date": "2020-01-01",
        "type": work_type,
        "cited_by_count": 5,
        "referenced_works": [],
        "authorships": [
            {
                "author": {"id": "https://openalex.org/A1", "display_name": "Author One"},
                "author_position": "first",
                "raw_author_name": "Author One",
            }
        ],
        "primary_location": {
            "source": {"id": "https://openalex.org/S1", "display_name": venue},
        },
    }


def crossref_envelope(doi: str, venue: str | None, work_type: str) -> dict:
    message = {"DOI": doi, "type": work_type}
    if venue is not None:
        message["container-title"] = [venue]
    return {"status": "ok", "message-type": "work", "message": message}


# W1: a single Crossref assertion that agrees on both venue and type.
# W2: a single Crossref assertion that disagrees on both.
# W3: no Crossref assertion at all.
# W4: two Crossref assertions -- one agrees, one disagrees -- so the combined
#     status must be "disagree" even though not every observation is, and the
#     exported list must carry both, ordered by raw_sha.
WORKS = {
    "W1": ("10.5555/w1", "Journal of Testing", "article"),
    "W2": ("10.5555/w2", "Journal of Testing", "article"),
    "W3": ("10.5555/w3", "Journal of Testing", "article"),
    "W4": ("10.5555/w4", "Journal of Testing", "article"),
}

ENVELOPES = {
    "W1": [("10.5555/w1", "Journal of Testing", "journal-article")],
    "W2": [("10.5555/w2", "Completely Different Venue", "book-chapter")],
    "W4": [
        ("10.5555/w4", "Journal of Testing", "journal-article"),
        ("10.5555/w4", "Some Other Venue", "book-chapter"),
    ],
}


def stage(tmp: Path) -> dict[str, str | list[str]]:
    shas: dict[str, str | list[str]] = {}
    for wid, (doi, venue, work_type) in WORKS.items():
        shas[wid] = store_payload(
            tmp,
            {"results": [openalex_work(wid, f"https://doi.org/{doi}", venue, work_type)]},
            f"file://openalex-{wid}",
        )
    for wid, envelopes in ENVELOPES.items():
        hashes = []
        for i, (doi, venue, work_type) in enumerate(envelopes):
            hashes.append(store_payload(
                tmp, crossref_envelope(doi, venue, work_type), f"file://crossref-{wid}-{i}",
            ))
        shas[f"crossref-{wid}"] = hashes
    return shas


def main() -> int:
    bad = 0

    # -- quality.assess(): disagree weakens, unavailable/incomparable/absent don't --
    GOOD = dict(title="A Sound Record", doi="https://doi.org/10.1023/a:1010933404324",
                year=2001, n_authors=1, referenced_count=16, cited_by_count=131109)

    baseline_band, baseline_evidence = Q.assess(**GOOD)
    bad += check(baseline_band == Q.COMPLETE, "a sound record with no source-comparison kwargs was not complete")
    baseline_signals = {(e["signal"], e["direction"]) for e in baseline_evidence}
    bad += check(("venue_source", "neutral") in baseline_signals,
                 "an absent venue_status did not record a neutral venue_source signal")
    bad += check(("work_type_source", "neutral") in baseline_signals,
                 "an absent work_type_status did not record a neutral work_type_source signal")

    for status in ("unavailable", "incomparable"):
        band, evidence = Q.assess(**GOOD, venue_status=status, work_type_status=status)
        bad += check(band == Q.COMPLETE, f"{status} venue/type statuses weakened the band to {band}")
        bad += check(
            all(e["direction"] == "neutral" for e in evidence if e["signal"] in ("venue_source", "work_type_source")),
            f"{status} did not produce a neutral direction",
        )

    agree_band, _ = Q.assess(**GOOD, venue_status="agree", work_type_status="agree")
    bad += check(agree_band == Q.COMPLETE, "agreeing venue/type statuses weakened a sound record")

    disagree_band, disagree_evidence = Q.assess(**GOOD, venue_status="disagree", work_type_status=None)
    bad += check(disagree_band == Q.PARTIAL, f"a single venue disagreement did not weaken the band: {disagree_band}")
    venue_entry = next(e for e in disagree_evidence if e["signal"] == "venue_source")
    bad += check(venue_entry["direction"] == "weakens", "a disagree venue_status was not recorded as weakens")
    bad += check(
        venue_entry["direction"] in Q.NOTE_TEMPLATES["venue_source"]
        and next(e for e in disagree_evidence if e["signal"] == "work_type_source")["direction"]
            in Q.NOTE_TEMPLATES["work_type_source"],
        "a venue_source/work_type_source direction has no note template",
    )

    both_disagree_band, _ = Q.assess(**GOOD, venue_status="disagree", work_type_status="disagree")
    bad += check(both_disagree_band == Q.SUSPECT, "two source disagreements did not reach suspect")

    # -- export + score_quality against a fixture corpus --------------------
    tmp = Path(tempfile.mkdtemp())
    saved = (derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH, export_json.ROOT)
    try:
        shas = stage(tmp)
        derive.RAW = tmp / "raw"
        derive.MANIFEST = tmp / "manifest.jsonl"

        conn = db.connect(tmp / "corpus.db")
        derive.load(conn)
        derive.score_quality(conn)
        derive.score_identities(conn)
        db.set_meta(conn, "derived_at", "2026-09-17T00:00:00+00:00")
        conn.commit()

        expected_status = {"W1": "agree", "W2": "disagree", "W3": "unavailable", "W4": "disagree"}

        for wid, status in expected_status.items():
            row = conn.execute(
                "SELECT quality_evidence FROM work WHERE id = ?", (wid,)
            ).fetchone()
            evidence = Q.decode_evidence(row["quality_evidence"])
            by_signal = {e["signal"]: e for e in evidence}
            bad += check("venue_source" in by_signal and "work_type_source" in by_signal,
                         f"{wid} quality_evidence is missing the new signals: {sorted(by_signal)}")
            expected_direction = {"agree": "supports", "disagree": "weakens", "unavailable": "neutral"}[status]
            bad += check(by_signal["venue_source"]["direction"] == expected_direction,
                         f"{wid} venue_source direction {by_signal['venue_source']['direction']!r}, "
                         f"expected {expected_direction!r}")
            bad += check(by_signal["work_type_source"]["direction"] == expected_direction,
                         f"{wid} work_type_source direction {by_signal['work_type_source']['direction']!r}, "
                         f"expected {expected_direction!r}")

        conn.close()

        export_json.OUT = tmp / "data"
        export_json.DB_PATH = tmp / "corpus.db"
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "export failed")

        works = {}
        for path in (tmp / "data" / "works").glob("*.json"):
            works.update(json.loads(path.read_text()))
        payloads = json.loads((tmp / "data" / "payloads.json").read_text())

        for wid, status in expected_status.items():
            comparison = works[wid].get("source_comparison")
            bad += check(comparison is not None, f"{wid} exported no source_comparison block")
            if comparison is None:
                continue
            role = comparison.get("role", "")
            bad += check("Crossref" in role and "parallel" in role.lower() and "correct" in role.lower(),
                         f"{wid} source_comparison does not state Crossref's parallel, uncorrected role")

            for field, value in (("venue", WORKS[wid][1]), ("work_type", WORKS[wid][2])):
                block = comparison[field]
                bad += check(block["status"] == status,
                             f"{wid} {field} status {block['status']!r}, expected {status!r}")
                bad += check(block["openalex"] == {"source": "OpenAlex", "value": value, "raw": shas[wid]},
                             f"{wid} {field} OpenAlex observation wrong: {block['openalex']}")

                expected_hashes = shas.get(f"crossref-{wid}", [])
                got_hashes = [c["raw"] for c in block["crossref"]]
                bad += check(got_hashes == sorted(expected_hashes),
                             f"{wid} {field} Crossref observations not ordered by raw_sha: {got_hashes}")
                for c in block["crossref"]:
                    bad += check(c["source"] == "Crossref", f"{wid} {field} Crossref observation mislabeled")
                    bad += check(c["raw"] in payloads,
                                 f"{wid} {field} Crossref raw hash {c['raw']} does not resolve in payloads.json")
                bad += check(block["openalex"]["raw"] in payloads,
                             f"{wid} {field} OpenAlex raw hash does not resolve in payloads.json")

        # W3 has no Crossref assertion: both fields must carry an empty list.
        w3 = works["W3"]["source_comparison"]
        bad += check(w3["venue"]["crossref"] == [] and w3["work_type"]["crossref"] == [],
                     "W3 (no Crossref assertion) exported a non-empty Crossref list")

        # W4's two envelopes disagree with each other on venue value; both must
        # still be present and individually attributed to their own raw hash.
        w4_venue_values = {c["value"] for c in works["W4"]["source_comparison"]["venue"]["crossref"]}
        bad += check(w4_venue_values == {"Journal of Testing", "Some Other Venue"},
                     f"W4 did not export both distinct Crossref venue observations: {w4_venue_values}")
    finally:
        derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH, export_json.ROOT = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_venue_type_export:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
