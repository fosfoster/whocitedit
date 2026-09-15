#!/usr/bin/env python3
"""Synthetic export coverage for the normalized corpus field browse index."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import corpus_contract
import db
import derive
import export_json
import graph
from test_field_membership import author, load_fixture, work


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def export_fixture(tmp, definition, observations):
    conn, db_path = load_fixture(tmp, definition, observations)
    graph.build_coauthorship(conn, 2026)
    derive.score_quality(conn)
    derive.score_identities(conn)
    db.set_meta(conn, "derived_at", "2026-09-15T00:00:00+00:00")
    conn.commit()
    author_ids = [row["id"] for row in conn.execute("SELECT id FROM author ORDER BY id")]
    conn.close()

    saved = (export_json.ROOT, export_json.DB_PATH, export_json.OUT)
    export_json.ROOT = tmp
    export_json.DB_PATH = db_path
    export_json.OUT = tmp / "data"
    try:
        if export_json.main() != 0:
            raise RuntimeError("export failed")
    finally:
        export_json.ROOT, export_json.DB_PATH, export_json.OUT = saved
    return tmp / "data", author_ids


def exported_work_payloads(data):
    return {
        work_id: payload
        for path in (data / "works").glob("*.json")
        for work_id, payload in json.loads(path.read_text()).items()
    }


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    fields = {
        "fields": {
            "zeta": {
                "name": "Zeta Field",
                "seed_filter": "topic.id:T-zeta",
                "max_works": 2,
            },
            "alpha": {
                "name": "Alpha Field",
                "description": "The first synthetic field.",
                "seed_filter": "topic.id:T-alpha",
                "max_works": 2,
            },
        }
    }
    try:
        data, author_ids = export_fixture(
            tmp,
            fields,
            [
                ({"results": [work("W-overlap", "A-overlap")]}, ["zeta", "alpha"]),
                ({"results": [work("W-alpha", "A-alpha")]}, ["alpha"]),
                ({"results": [work("W-zeta", "A-zeta")]}, ["zeta"]),
                ({"results": [author("A-overlap"), author("A-alpha"), author("A-zeta")]}, [None]),
            ],
        )

        field_index = json.loads((data / "fields-index.json").read_text())
        bad += check(
            field_index == [
                {
                    "key": "alpha",
                    "name": "Alpha Field",
                    "description": "The first synthetic field.",
                    "works": 2,
                },
                {
                    "key": "zeta",
                    "name": "Zeta Field",
                    "description": None,
                    "works": 2,
                },
            ],
            "fields index did not retain normalized metadata in key order",
        )

        payloads = exported_work_payloads(data)
        expected_fields = {
            "W-alpha": ["alpha"],
            "W-overlap": ["alpha", "zeta"],
            "W-zeta": ["zeta"],
        }
        bad += check(
            {wid: payloads[wid]["fields"] for wid in sorted(payloads)} == expected_fields,
            "work payload fields were changed while building the field index",
        )
        work_index = json.loads((data / "works-index.json").read_text())
        bad += check(
            {row["id"]: row["fields"] for row in work_index} == expected_fields
            and len(work_index) == 3,
            "field overlap duplicated or changed work exports",
        )
        author_index = json.loads((data / "authors-index.json").read_text())
        bad += check(
            sorted(row["id"] for row in author_index) == author_ids and len(author_index) == 3,
            "field overlap changed exported author IDs or count",
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    legacy_tmp = Path(tempfile.mkdtemp())
    legacy = {
        "name": "Legacy Synthetic Field",
        "description": "A legacy field definition.",
        "seed_filter": "topic.id:T-legacy",
        "max_works": 1,
    }
    try:
        data, _ = export_fixture(
            legacy_tmp,
            legacy,
            [({"results": [work("W-legacy", "A-legacy")]}, [None]),
             ({"results": [author("A-legacy")]}, [None])],
        )
        legacy_key = corpus_contract.field_key(legacy["name"])
        bad += check(
            json.loads((data / "fields-index.json").read_text()) == [
                {
                    "key": legacy_key,
                    "name": legacy["name"],
                    "description": legacy["description"],
                    "works": 1,
                }
            ],
            "legacy field did not receive its deterministic normalized key",
        )
    finally:
        shutil.rmtree(legacy_tmp, ignore_errors=True)

    print("test_field_index_export:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
