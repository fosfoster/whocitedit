#!/usr/bin/env python3
"""Offline coverage for work field membership in the compact global search index."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import corpus_contract
import derive
import export_json
import render
import test_entity_export
import test_legacy_field_membership as legacy


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def work_fields_from_shards(data: Path) -> dict:
    """The wid -> field keys mapping render derives from the work shards.

    Same source ``render.search_index`` is fed from (``main()``'s
    ``work_fields``) -- not the browse-index row.
    """
    work_fields = {}
    for shard in sorted((data / "works").glob("*.json")):
        for wid, w in json.loads(shard.read_text()).items():
            work_fields[wid] = w.get("fields", [])
    return work_fields


def search_index_records(site: Path) -> list[dict]:
    path = site / "data" / "search-index.json"
    return json.loads(path.read_text()) if path.exists() else []


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH,
             export_json.ROOT, render.DATA, render.SITE, render.ASSETS)
    try:
        render.ASSETS = Path(__file__).parent / "web" / "assets"

        # -- export-driven path: every work carries its exported field keys --
        db_path, _, _ = test_entity_export.build_corpus(tmp)
        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "synthetic export failed")

        render.DATA = tmp / "data"
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "synthetic render failed")

        work_fields = work_fields_from_shards(render.DATA)
        bad += check(bool(work_fields) and all(work_fields.values()),
                     "fixture produced no work field memberships to assert against")

        records = search_index_records(render.SITE)
        work_records = {row["id"]: row for row in records if row["kind"] == "work"}
        bad += check(bool(work_records), "no work records in the search index")
        bad += check(
            all(work_records[wid]["fields"] == fields for wid, fields in work_fields.items()),
            "a work record's fields do not match the fields render derived for that work")
        bad += check(
            all("fields" not in row for row in records if row["kind"] != "work"),
            "a non-work search record carries a fields key")

        first = (render.SITE / "data" / "search-index.json").read_bytes()
        bad += check(render.main() == 0, "repeat synthetic render failed")
        second = (render.SITE / "data" / "search-index.json").read_bytes()
        bad += check(first == second,
                     "repeating the render changed search-index.json bytes")

        # -- legacy path: no fields-index.json, no fields on rows or shards --
        definition = {
            "name": "Artificial Intelligence & Robotics",
            "description": "One legacy field.",
            "max_works": 3,
        }
        legacy_key = corpus_contract.field_key(definition["name"])
        legacy_works = [
            legacy.index_row("W-legacy-first", "Legacy first", 2024),
            legacy.index_row("W-legacy-second", "Legacy second", 2023),
            legacy.index_row("W-legacy-third", "Legacy third", 2022),
        ]
        legacy_data = tmp / "legacy-data"
        legacy.write_fixture(legacy_data, definition, legacy_works)
        bad += check(
            all("fields" not in row for row in json.loads(
                (legacy_data / "works-index.json").read_text()))
            and all("fields" not in payload for payload in json.loads(
                (legacy_data / "works" / "fixture.json").read_text()).values())
            and not (legacy_data / "fields-index.json").exists(),
            "legacy fixture was not written without any field export surface")

        render.DATA = legacy_data
        render.SITE = tmp / "legacy-site"
        bad += check(render.main() == 0, "legacy render failed")

        legacy_records = search_index_records(render.SITE)
        legacy_work_records = {row["id"]: row for row in legacy_records if row["kind"] == "work"}
        bad += check(sorted(legacy_work_records) == sorted(work["id"] for work in legacy_works),
                     "legacy search index did not contain a record for every legacy work")
        bad += check(
            all(record["fields"] == [legacy_key] for record in legacy_work_records.values()),
            "legacy work records did not fall back to the single normalized field key")
        bad += check(
            all("fields" not in row for row in legacy_records if row["kind"] != "work"),
            "a non-work legacy search record carries a fields key")
    finally:
        (derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH,
         export_json.ROOT, render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_search_index_fields:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
