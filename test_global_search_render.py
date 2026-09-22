#!/usr/bin/env python3
"""Offline coverage for the compact global search index rendered from exports."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import derive
import export_json
import render
import test_entity_export


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def work_fields_from_shards(data: Path) -> dict:
    """The wid -> field keys mapping render derives from the work shards.

    This is the same source ``render.search_index`` is fed from (``main()``'s
    ``work_fields``), not the browse-index row -- a legacy corpus has no
    ``fields`` key on its works-index rows at all.
    """
    work_fields = {}
    for shard in sorted((data / "works").glob("*.json")):
        for wid, w in json.loads(shard.read_text()).items():
            work_fields[wid] = w.get("fields", [])
    return work_fields


def expected_records(data: Path, collections) -> list[dict]:
    state_fields = {"work": "quality", "author": "band"}
    work_fields = work_fields_from_shards(data)
    return [
        {
            "kind": kind,
            "id": row["id"],
            "label": row[label],
            **({"state": row[state_fields[kind]]} if kind in state_fields else {}),
            **({"fields": work_fields[row["id"]]}
               if kind == "work" and work_fields.get(row["id"]) else {}),
        }
        for kind, index, label in collections
        for row in json.loads((data / index).read_text())
    ]


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH,
             export_json.ROOT, render.DATA, render.SITE, render.ASSETS)
    collections = (
        ("work", "works-index.json", "title"),
        ("author", "authors-index.json", "name"),
        ("institution", "institutions-index.json", "name"),
        ("topic", "topics-index.json", "name"),
    )
    try:
        db_path, _, _ = test_entity_export.build_corpus(tmp)
        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "synthetic export failed")

        render.DATA = tmp / "data"
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "synthetic render failed")

        index_path = render.SITE / "data" / "search-index.json"
        records = json.loads(index_path.read_text()) if index_path.exists() else []
        expected = expected_records(render.DATA, collections)
        bad += check(records == expected,
                     "search index does not project every collection in fixed kind order")
        expected_states = {
            **{
                ("work", row["id"]): row["quality"]
                for row in json.loads((render.DATA / "works-index.json").read_text())
            },
            **{
                ("author", row["id"]): row["band"]
                for row in json.loads((render.DATA / "authors-index.json").read_text())
            },
        }
        actual_states = {
            (record["kind"], record["id"]): record["state"]
            for record in records if record["kind"] in ("work", "author") and "state" in record
        }
        bad += check(
            actual_states == expected_states,
            "work quality and author confidence states do not match their sources")
        bad += check(
            all("state" not in record for record in records
                if record["kind"] in ("institution", "topic")),
            "institution and topic search records carry state")
        work_fields = work_fields_from_shards(render.DATA)
        bad += check(
            all(set(record) == (
                {"kind", "id", "label"}
                | ({"state"} if record["kind"] in ("work", "author") else set())
                | ({"fields"} if record["kind"] == "work" and work_fields.get(record["id"]) else set())
            ) for record in records),
            "search records do not have the expected compact schema")
        bad += check(len({(record["kind"], record["id"]) for record in records}) == len(records),
                     "search index contains duplicate entity records")

        first = index_path.read_bytes() if index_path.exists() else b""
        bad += check(render.main() == 0, "repeat synthetic render failed")
        bad += check(index_path.exists() and index_path.read_bytes() == first,
                     "repeating the render changed search-index.json bytes")

        legacy = tmp / "legacy-data"
        shutil.copytree(render.DATA, legacy)
        for name in ("institutions-index.json", "topics-index.json"):
            (legacy / name).unlink()
        for directory in (legacy / "institutions", legacy / "topics"):
            shutil.rmtree(directory)
        render.DATA = legacy
        render.SITE = tmp / "legacy-site"
        bad += check(render.main() == 0, "legacy render failed")
        legacy_index = render.SITE / "data" / "search-index.json"
        legacy_records = json.loads(legacy_index.read_text()) if legacy_index.exists() else []
        bad += check(legacy_records == expected_records(legacy, collections[:2]),
                     "legacy search index did not contain exactly work and author records")
    finally:
        (derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH,
         export_json.ROOT, render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_global_search_render:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
