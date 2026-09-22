#!/usr/bin/env python3
"""Citation-count outlier evidence is selected-corpus-relative and read-only."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import db
import derive
import export_json
import quality


ROOT = Path(__file__).parent
RAW_SHA = "fixture"


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def works_fixture() -> list[dict]:
    works = [
        {"id": "W-high", "year": 2020, "venue": "S-exact", "count": 10000},
        {"id": "W-low", "year": 2020, "venue": "S-exact", "count": 10},
        {"id": "W-other-year", "year": 2021, "venue": "S-exact", "count": 10000},
        {"id": "W-other-venue", "year": 2020, "venue": "S-other", "count": 10000},
        {"id": "W-missing-year", "year": None, "venue": "S-exact", "count": 10000},
        {"id": "W-missing-venue", "year": 2020, "venue": None, "count": 10000},
        {"id": "W-small", "year": 2022, "venue": "S-small", "count": 10000},
        {"id": "W-tukey-guard", "year": 2023, "venue": "S-tukey", "count": 500},
        {"id": "W-median-guard", "year": 2024, "venue": "S-median", "count": 200},
    ]
    works.extend(
        {"id": f"W-exact-peer-{i}", "year": 2020, "venue": "S-exact", "count": 10}
        for i in range(8)
    )
    works.extend(
        {"id": f"W-small-peer-{i}", "year": 2022, "venue": "S-small", "count": 10}
        for i in range(7)
    )
    works.extend(
        {"id": f"W-tukey-peer-{i}", "year": 2023, "venue": "S-tukey", "count": count}
        for i, count in enumerate([10, 10, 10, 10, 100, 100, 100, 100])
    )
    works.extend(
        {"id": f"W-median-peer-{i}", "year": 2024, "venue": "S-median", "count": 100}
        for i in range(8)
    )
    return works


def insert_work(conn, work: dict) -> None:
    evidence = json.dumps([{"signal": "title", "value": "fixture", "direction": "supports"}])
    conn.execute(
        "INSERT INTO work("
        "id, title, year, source_id, source_name, abstract_reason, cited_by_count, "
        "quality, quality_evidence, raw_sha) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            work["id"],
            work["id"],
            work["year"],
            work["venue"],
            f"Venue {work['venue']}" if work["venue"] else None,
            "withheld",
            work["count"],
            quality.PARTIAL,
            evidence,
            RAW_SHA,
        ),
    )


def snapshot(conn) -> bytes:
    rows = [
        dict(row)
        for row in conn.execute(
            "SELECT id, cited_by_count, quality, quality_evidence FROM work ORDER BY id"
        )
    ]
    return json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()


def stage(path: Path, works: list[dict]):
    conn = db.connect(path)
    conn.execute(
        "INSERT INTO raw_payload(sha256, url, fetched_at, path) VALUES(?,?,?,?)",
        (RAW_SHA, "fixture://citation-outlier", "2026-09-21T00:00:00+00:00", "fixture.json"),
    )
    for work in works:
        insert_work(conn, work)
    conn.commit()
    return conn


def all_evidence(conn) -> dict[str, dict | None]:
    return {
        row["id"]: derive.citation_count_outlier(conn, row)
        for row in conn.execute("SELECT * FROM work ORDER BY id")
    }


def load_exported_works(out: Path) -> dict:
    works = {}
    for path in (out / "works").glob("*.json"):
        works.update(json.loads(path.read_text()))
    return works


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (export_json.OUT, export_json.DB_PATH, export_json.ROOT)
    try:
        fixture = works_fixture()
        conn = stage(tmp / "corpus.db", fixture)
        before = snapshot(conn)
        evidence = all_evidence(conn)
        bulk_evidence = derive.citation_count_outliers(conn)
        after_derivation = snapshot(conn)

        high = evidence["W-high"]
        bad += check(high is not None, "an extreme exact-year-and-venue value was not flagged")
        if high:
            bad += check(high["observed_openalex_citation_count"] == 10000,
                         "outlier evidence changed the observed OpenAlex count")
            bad += check(high["year"] == 2020, "outlier evidence omitted the publication year")
            bad += check(high["venue"] == {"id": "S-exact", "name": "Venue S-exact"},
                         "outlier evidence omitted the stable venue ID or name")
            bad += check(high["peer_count"] == 9,
                         "the subject was not excluded from its exact cohort")
            bad += check(high["peer_median"] == 10, "outlier evidence has the wrong peer median")
            bad += check(high["effective_threshold"] == max(
                high["log1p_upper_outer_fence"], high["five_times_peer_median"]
            ), "effective threshold does not require both conservative guards")
            bad += check("selected corpus peers" in high["basis"].lower()
                         and "not a population estimate" in high["basis"].lower(),
                         "outlier evidence does not say it is selected-corpus-relative")
        bad += check(bulk_evidence.get("W-high") == high,
                     "bulk derivation differs from the single-work derivation")

        for wid in (
            "W-other-year", "W-other-venue", "W-missing-year", "W-missing-venue",
            "W-small", "W-low",
        ):
            bad += check(evidence[wid] is None, f"{wid} exported an unwarranted outlier warning")
        bad += check(
            evidence["W-tukey-guard"] is None,
            "a value that passes the five-times-median guard but fails the log1p outer fence warned",
        )
        bad += check(
            evidence["W-median-guard"] is None,
            "a value that passes the log1p outer fence but fails the five-times-median guard warned",
        )
        bad += check(before == after_derivation,
                     "read-only derivation changed work IDs, counts, quality, or quality evidence")

        reversed_conn = stage(tmp / "reversed.db", list(reversed(fixture)))
        reversed_evidence = all_evidence(reversed_conn)
        bad += check(reversed_evidence == evidence,
                     "citation outlier evidence depends on source insertion order")
        reversed_conn.close()

        conn.close()
        export_json.OUT = tmp / "data"
        export_json.DB_PATH = tmp / "corpus.db"
        export_json.ROOT = ROOT
        bad += check(export_json.main() == 0, "synthetic export failed")

        exported = load_exported_works(export_json.OUT)
        exported_high = exported["W-high"]
        bad += check(exported_high["citation_count_outlier"] == high,
                     "the qualifying work did not export its citation-count evidence")
        for wid in (
            "W-other-year", "W-other-venue", "W-missing-year", "W-missing-venue",
            "W-small", "W-low", "W-tukey-guard", "W-median-guard",
        ):
            bad += check(exported[wid]["citation_count_outlier"] is None,
                         f"{wid} did not export a nullable no-warning result")
        expected_quality = {
            "band": quality.PARTIAL,
            "sentence": quality.band_sentence(quality.PARTIAL),
            "evidence": [{"signal": "title", "value": "fixture", "direction": "supports"}],
        }
        bad += check(exported_high["quality"] == expected_quality,
                     "the exported quality object changed when outlier evidence was added")

        post_export = db.connect(tmp / "corpus.db")
        bad += check(snapshot(post_export) == before,
                     "export changed work IDs, counts, quality, or quality evidence")
        post_export.close()
    finally:
        (export_json.OUT, export_json.DB_PATH, export_json.ROOT) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_citation_outlier_export:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
