#!/usr/bin/env python3
"""Synthetic end-to-end coverage for many-to-many corpus field membership."""
import hashlib
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


ROOT = Path(__file__).parent


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def work(wid, aid):
    return {
        "id": f"https://openalex.org/{wid}",
        "title": f"Fixture {wid}",
        "publication_year": 2024,
        "publication_date": "2024-01-01",
        "type": "article",
        "open_access": {"is_oa": False},
        "authorships": [{
            "author": {"id": f"https://openalex.org/{aid}", "display_name": f"Author {aid}"},
            "author_position": "first",
        }],
        "referenced_works": [],
    }


def author(aid):
    return {
        "id": f"https://openalex.org/{aid}",
        "display_name": f"Author {aid}",
        "works_count": 1,
        "cited_by_count": 0,
    }


def store(raw, payload):
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sha = hashlib.sha256(body).hexdigest()
    path = raw / sha[:2] / f"{sha}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return sha, path


def write_observation(manifest, sha, path, root, field_key=None):
    record = {
        "url": "https://api.openalex.org/works",
        "sha256": sha,
        "fetched_at": "2026-09-15T00:00:00+00:00",
        "path": str(path.relative_to(root)),
    }
    if field_key is not None:
        record["field_key"] = field_key
    with manifest.open("a") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def load_fixture(tmp, definition, observations):
    """Write raw observations, derive them, and return the temporary database."""
    corpus = tmp / "corpus.json"
    corpus.write_text(json.dumps(definition))
    raw = tmp / "harvest" / "raw"
    manifest = tmp / "harvest" / "manifest.jsonl"
    for payload, field_keys in observations:
        sha, path = store(raw, payload)
        for field_key in field_keys:
            write_observation(manifest, sha, path, tmp, field_key)

    saved = (derive.ROOT, derive.RAW, derive.MANIFEST, derive.CORPUS)
    derive.ROOT = tmp
    derive.RAW = raw
    derive.MANIFEST = manifest
    derive.CORPUS = corpus
    conn = db.connect(tmp / "fixture.db")
    try:
        derive.load(conn)
        conn.commit()
    except Exception:
        conn.close()
        raise
    finally:
        derive.ROOT, derive.RAW, derive.MANIFEST, derive.CORPUS = saved
    return conn, tmp / "fixture.db"


def expect_rejected(definition, field_keys, phrase):
    tmp = Path(tempfile.mkdtemp())
    try:
        try:
            conn, _ = load_fixture(tmp, definition, [({"results": [work("W-bad", "A-bad")]}, field_keys)])
        except ValueError as exc:
            return phrase in str(exc)
        else:
            conn.close()
            return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    fields = {
        "fields": {
            "practice": {"name": "Practice", "seed_filter": "topic.id:T-practice", "max_works": 2},
            "theory": {"name": "Theory", "seed_filter": "topic.id:T-theory", "max_works": 2},
        }
    }
    author_ids = ["A-overlap", "A-practice", "A-theory"]
    try:
        # The same payload hash is observed by both fields.  A later manifest
        # observation must add to, not replace, the first field membership.
        conn, db_path = load_fixture(
            tmp,
            fields,
            [
                ({"results": [work("W-overlap", "A-overlap")]}, ["theory", "practice"]),
                ({"results": [work("W-practice", "A-practice")]}, ["practice"]),
                ({"results": [work("W-theory", "A-theory")]}, ["theory"]),
                ({"results": [author(aid) for aid in author_ids]}, [None]),
            ],
        )
        memberships = {
            row["work_id"]: row["fields"].split(",")
            for row in conn.execute(
                "SELECT work_id, GROUP_CONCAT(field_key, ',') fields "
                "FROM (SELECT work_id, field_key FROM work_corpus_field ORDER BY field_key) "
                "GROUP BY work_id"
            )
        }
        bad += check(
            memberships == {
                "W-overlap": ["practice", "theory"],
                "W-practice": ["practice"],
                "W-theory": ["theory"],
            },
            f"database field memberships were not complete and sorted: {memberships}",
        )
        bad += check(
            conn.execute("SELECT COUNT(*) c FROM work_corpus_field WHERE work_id = 'W-overlap'").fetchone()["c"] == 2,
            "overlapping work did not receive two work_corpus_field rows",
        )
        bad += check(
            conn.execute("SELECT COUNT(*) c FROM corpus_field").fetchone()["c"] == 2,
            "normalized corpus definitions were not persisted",
        )
        bad += check(
            [row["id"] for row in conn.execute("SELECT id FROM author ORDER BY id")] == author_ids,
            "field overlap changed fixture author identities before export",
        )
        graph.build_coauthorship(conn, 2026)
        derive.score_quality(conn)
        derive.score_identities(conn)
        db.set_meta(conn, "derived_at", "2026-09-15T00:00:00+00:00")
        conn.commit()
        conn.close()

        saved = (export_json.ROOT, export_json.DB_PATH, export_json.OUT)
        export_json.ROOT = tmp
        export_json.DB_PATH = db_path
        export_json.OUT = tmp / "data"
        try:
            bad += check(export_json.main() == 0, "export failed")
        finally:
            export_json.ROOT, export_json.DB_PATH, export_json.OUT = saved

        corpus = json.loads((tmp / "data" / "corpus.json").read_text())
        index = json.loads((tmp / "data" / "works-index.json").read_text())
        authors = json.loads((tmp / "data" / "authors-index.json").read_text())
        payloads = {
            wid: payload
            for path in (tmp / "data" / "works").glob("*.json")
            for wid, payload in json.loads(path.read_text()).items()
        }
        bad += check(corpus["definition"] == fields,
                     "export no longer retained the legacy definition surface")
        bad += check(corpus["fields"] == fields["fields"],
                     "export did not emit every normalized named definition")
        expected_fields = {
            "W-overlap": ["practice", "theory"],
            "W-practice": ["practice"],
            "W-theory": ["theory"],
        }
        bad += check({wid: payloads[wid]["fields"] for wid in sorted(payloads)} == expected_fields,
                     "work shard payloads did not carry complete sorted field keys")
        bad += check({row["id"]: row["fields"] for row in index} == expected_fields,
                     "works-index rows did not carry complete sorted field keys")
        bad += check(sorted(payloads) == sorted(expected_fields) and len(payloads) == 3,
                     "fixture works were merged, split, dropped, or exported more than once")
        bad += check([row["id"] for row in sorted(authors, key=lambda row: row["id"])] == author_ids
                     and len(authors) == 3,
                     "field overlap changed fixture author IDs or exported author row count")

        legacy = json.loads((ROOT / "corpus.json").read_text())
        legacy_key = corpus_contract.field_key(legacy["name"])
        legacy_tmp = Path(tempfile.mkdtemp())
        try:
            legacy_conn, _ = load_fixture(
                legacy_tmp,
                legacy,
                [({"results": [work("W-legacy", "A-legacy")]}, [None])],
            )
            legacy_fields = [
                row["field_key"]
                for row in legacy_conn.execute(
                    "SELECT field_key FROM work_corpus_field WHERE work_id = 'W-legacy'"
                )
            ]
            legacy_conn.close()
            bad += check(legacy_fields == [legacy_key],
                         "legacy untagged work did not fall back to the repository's sole field")
        finally:
            shutil.rmtree(legacy_tmp, ignore_errors=True)

        bad += check(expect_rejected(fields, ["practice", None], "missing field membership"),
                     "multi-field derivation accepted incomplete field provenance")
        bad += check(expect_rejected(fields, ["not-a-field"], "unknown field membership"),
                     "multi-field derivation accepted a work with an unknown field provenance")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_field_membership:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
