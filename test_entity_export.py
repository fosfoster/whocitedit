"""Offline end-to-end coverage for institution and topic entity exports."""
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import db
import derive
import export_json
import graph


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def store_payload(root: Path, payload: dict, url: str) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sha = hashlib.sha256(body).hexdigest()
    path = root / "raw" / sha[:2] / f"{sha}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    with (root / "manifest.jsonl").open("a") as fh:
        fh.write(json.dumps({
            "sha256": sha,
            "url": url,
            "fetched_at": "2026-09-03T00:00:00+00:00",
            "path": str(path.relative_to(root)),
        }, sort_keys=True) + "\n")
    return sha


def work(wid: str, title: str, cited: int, author_ids: list[str]) -> dict:
    return {
        "id": f"https://openalex.org/{wid}",
        "title": title,
        "publication_year": 2020,
        "publication_date": "2020-01-01",
        "type": "article",
        "cited_by_count": cited,
        "referenced_works": [],
        "primary_location": {
            "source": {"id": "https://openalex.org/S1", "display_name": "Journal"},
        },
        "topics": [{
            "id": "https://openalex.org/T1",
            "display_name": "Synthetic Science",
            "score": 0.9,
            "field": {"display_name": "Computer Science"},
            "domain": {"display_name": "Physical Sciences"},
        }],
        "authorships": [{
            "author": {
                "id": f"https://openalex.org/{aid}",
                "display_name": f"Author {aid}",
            },
            "author_position": "first" if i == 0 else "middle",
            "raw_author_name": f"Author {aid}",
            "institutions": [{
                "id": "https://openalex.org/I-AFF",
                "display_name": "Affiliated Institute",
                "ror": "https://ror.org/aff",
                "country_code": "US",
                "type": "education",
            }],
        } for i, aid in enumerate(author_ids)],
    }


def build_corpus(tmp: Path) -> tuple[Path, set[str], str]:
    author_ids = [f"A{i:02d}" for i in range(1, 27)]
    work_payloads = [
        work("W1", "Most Cited Work", 30, author_ids),
        work("W2", "Second Work", 20, author_ids[:2]),
        work("W3", "Third Work", 10, [author_ids[0], author_ids[2]]),
    ]
    shas = {
        store_payload(tmp, {"results": [payload]}, f"file://{payload['id'].rsplit('/', 1)[-1]}")
        for payload in work_payloads
    }
    authors = [{
        "id": f"https://openalex.org/{aid}",
        "display_name": f"Author {aid}",
        "works_count": 3,
        "cited_by_count": 100 - i,
        "last_known_institutions": [{
            "id": "https://openalex.org/I-LAST",
            "display_name": "Last Known Institute",
            "ror": "https://ror.org/last",
            "country_code": "GB",
            "type": "education",
        }] if aid == "A01" else [],
    } for i, aid in enumerate(author_ids)]
    author_sha = store_payload(tmp, {"results": authors}, "file://authors")
    shas.add(author_sha)

    derive.RAW = tmp / "raw"
    derive.MANIFEST = tmp / "manifest.jsonl"
    conn = db.connect(tmp / "corpus.db")
    derive.load(conn)
    graph.build_coauthorship(conn, 2026)
    derive.score_identities(conn)
    conn.commit()
    conn.close()
    return tmp / "corpus.db", shas, author_sha


def read_shards(data: Path, directory: str, index_name: str) -> tuple[list[dict], dict[str, dict], list[str]]:
    index = json.loads((data / index_name).read_text())
    shards = {}
    shard_ids = []
    for path in sorted((data / directory).glob("*.json")):
        shard = json.loads(path.read_text())
        shard_ids.extend(shard)
        shards.update(shard)
    return index, shards, shard_ids


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*.json"))
    }


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH,
             export_json.ROOT)
    try:
        db_path, expected_payloads, author_sha = build_corpus(tmp)
        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "export failed")

        data = tmp / "data"
        institution_index, institutions, institution_shard_ids = read_shards(
            data, "institutions", "institutions-index.json"
        )
        topic_index, topics, topic_shard_ids = read_shards(
            data, "topics", "topics-index.json"
        )
        _, works, _ = read_shards(data, "works", "works-index.json")
        conn = db.connect(db_path)
        institution_ids = {r["id"] for r in conn.execute("SELECT id FROM institution")}
        topic_ids = {r["id"] for r in conn.execute("SELECT id FROM topic")}
        indexed_institutions = [r["id"] for r in institution_index]
        indexed_topics = [r["id"] for r in topic_index]
        bad += check(set(indexed_institutions) == institution_ids and
                     len(indexed_institutions) == len(institution_ids),
                     "institution index is not exactly the database table")
        bad += check(set(indexed_topics) == topic_ids and len(indexed_topics) == len(topic_ids),
                     "topic index is not exactly the database table")
        bad += check(set(institution_shard_ids) == institution_ids and
                     len(institution_shard_ids) == len(institution_ids),
                     "institution shards are not exactly the database table")
        bad += check(set(topic_shard_ids) == topic_ids and len(topic_shard_ids) == len(topic_ids),
                     "topic shards are not exactly the database table")
        bad += check(all({topic["id"] for topic in works[wid]["topics"]} == {"T1"}
                         for wid in ("W1", "W2", "W3")),
                     "a fixture work lost its topic during derivation/export")
        bad += check(all(conn.execute(
            "SELECT raw_sha FROM institution WHERE id = ?", (iid,)
        ).fetchone()["raw_sha"] for iid in institution_ids),
                     "an institution did not retain its metadata payload hash")
        bad += check(all(conn.execute(
            "SELECT raw_sha FROM topic WHERE id = ?", (tid,)
        ).fetchone()["raw_sha"] for tid in topic_ids),
                     "a topic did not retain its metadata payload hash")
        bad += check(institutions["I-AFF"]["works"] and
                     {w["id"] for w in institutions["I-AFF"]["works"]} == {"W1", "W2", "W3"},
                     "institution works were not selected through affiliation")
        bad += check(institutions["I-LAST"]["works"] == [] and
                     institutions["I-LAST"]["authors"] == [],
                     "last-known-only institution incorrectly gained affiliations")
        bad += check(len(institutions["I-AFF"]["authors"]) == 26, "affiliated author list was truncated")

        graph_blob = institutions["I-AFF"]["graph"]
        graph_ids = {node["id"] for node in graph_blob["nodes"]}
        author_ids = {author["id"] for author in institutions["I-AFF"]["authors"]}
        bad += check(graph_blob["shown"] < graph_blob["available"] == 26,
                     "institution graph did not report its truncation")
        bad += check(graph_ids <= author_ids, "institution graph contains a non-institution author")
        bad += check(all(edge["s"] in graph_ids and edge["t"] in graph_ids
                         for edge in graph_blob["edges"]),
                     "institution graph has an edge outside its node set")
        bad += check(all("x" in node and "y" in node for node in graph_blob["nodes"]),
                     "institution graph node has no coordinate")
        bad += check(all(len(topics[tid]["works"]) == 3 for tid in topics),
                     "fixture works did not retain their topic")
        topic = topics["T1"]
        bad += check([work["id"] for work in topic["works"]] == ["W1", "W2", "W3"],
                     "topic works are not ranked by citation count")
        bad += check(topic["authors"][0]["id"] == "A01" and
                     topic["authors"][0]["participation"] == 3,
                     "topic authors are not ranked by participation")

        payloads = json.loads((data / "payloads.json").read_text())
        bad += check(set(payloads) == expected_payloads, "payloads.json lost a fixture payload")
        for entity in list(institutions.values()) + list(topics.values()):
            bad += check(entity["raw"] and entity["raw"] == sorted(set(entity["raw"])),
                         f"unsorted or empty aggregate provenance: {entity['id']}")
            bad += check(set(entity["raw"]) <= set(payloads),
                         f"aggregate provenance does not resolve: {entity['id']}")
        bad += check(author_sha in institutions["I-LAST"]["raw"],
                     "last-known institution has no source payload")

        first = snapshot(data)
        bad += check(export_json.main() == 0, "repeat export failed")
        bad += check(first == snapshot(data), "repeating export changed JSON bytes")

        # Calling layout with the same graph inputs proves the exported
        # coordinates are not an accidental insertion-order artifact.
        coords_a = [(n["id"], n["x"], n["y"]) for n in graph_blob["nodes"]]
        coords_b = [(n["id"], n["x"], n["y"])
                    for n in institutions["I-AFF"]["graph"]["nodes"]]
        bad += check(coords_a == coords_b, "institution graph coordinates are not deterministic")
        conn.close()
    finally:
        (derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH,
         export_json.ROOT) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_entity_export:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
