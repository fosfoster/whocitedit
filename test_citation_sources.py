#!/usr/bin/env python3
"""Offline citation-source reconciliation and graph export coverage."""
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import db
import derive
import export_json


ROOT = Path(__file__).parent
OPENALEX = json.loads((ROOT / "docs" / "fixtures" / "openalex" / "citation-sources.json").read_text())
COCI = json.loads((ROOT / "docs" / "fixtures" / "opencitations" / "references.json").read_text())


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def store_payload(root: Path, payload, url: str) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sha = hashlib.sha256(body).hexdigest()
    path = root / "raw" / sha[:2] / f"{sha}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    with (root / "manifest.jsonl").open("a") as manifest:
        manifest.write(json.dumps({
            "sha256": sha,
            "url": url,
            "fetched_at": "2026-09-13T00:00:00+00:00",
            "path": str(path.relative_to(root)),
        }, sort_keys=True) + "\n")
    return sha


def edge_sources(graph_blob: dict) -> dict[tuple[str, str], list[str]]:
    return {(edge["s"], edge["t"]): edge["sources"] for edge in graph_blob["edges"]}


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH,
             export_json.ROOT)
    try:
        # The retained t1 COCI fixture provides the corroborated and COCI-only
        # assertions. These additional pairs must not make a dangling edge.
        coci = COCI + [
            {"citing": "https://doi.org/10.5555/SOURCE-PAPER",
             "cited": "doi:10.5555/does-not-exist"},
            {"citing": "10.5555/does-not-exist", "cited": "10.5555/reference-one"},
            {"citing": "10.5555/source-paper", "cited": "10.5555/source-paper"},
        ]
        store_payload(tmp, OPENALEX, "fixture://openalex/citation-sources")
        store_payload(tmp, coci, "fixture://opencitations/citation-sources")

        derive.RAW = tmp / "raw"
        derive.MANIFEST = tmp / "manifest.jsonl"
        db_path = tmp / "corpus.db"
        conn = db.connect(db_path)
        derive.load(conn)
        conn.commit()

        rows = {
            (row["citing_id"], row["cited_id"]): json.loads(row["sources"])
            for row in conn.execute("SELECT citing_id, cited_id, sources FROM citation")
        }
        bad += check(rows[("W1", "W2")] == ["openalex", "opencitations"],
                     "the shared edge did not retain both source assertions")
        bad += check(rows[("W4", "W3")] == ["openalex"],
                     "the OpenAlex-only edge changed sources")
        bad += check(rows[("W1", "W3")] == ["opencitations"],
                     "the COCI-only edge was not resolved")
        bad += check(set(rows) == {("W1", "W2"), ("W1", "W3"), ("W4", "W1"), ("W4", "W3")},
                     "unknown DOI endpoints made a dangling citation")
        bad += check(("W1", "W1") not in rows,
                     "a self-referential DOI pair made a citation")
        conn.close()

        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = ROOT
        bad += check(export_json.main() == 0, "export failed")
        work = json.loads(
            (tmp / "data" / "works" / f"{export_json.shard('W1')}.json").read_text()
        )["W1"]
        exported = edge_sources(work["graph"])
        bad += check(exported[("W1", "W2")] == ["openalex", "opencitations"],
                     "the direct shared edge lost its exported source list")
        bad += check(exported[("W1", "W3")] == ["opencitations"],
                     "the direct COCI-only edge lost its exported source list")
        bad += check(exported[("W4", "W1")] == ["openalex"],
                     "the direct OpenAlex-only edge lost its exported source list")
        bad += check(exported[("W4", "W3")] == ["openalex"],
                     "the inner neighbourhood edge lost its exported source list")
        bad += check(all(isinstance(edge["sources"], list) for edge in work["graph"]["edges"]),
                     "a graph edge exported encoded rather than decoded sources")

        corpus = json.loads((tmp / "data" / "corpus.json").read_text())
        coci_source = next((source for source in corpus["sources"]
                            if source["name"] == "OpenCitations COCI"), None)
        bad += check(coci_source == {
            "name": "OpenCitations COCI",
            "url": "https://opencitations.net/index/coci/",
            "license": "CC0",
            "role": "citation edges",
        }, "corpus metadata does not declare COCI's CC0 citation-edge role")
    finally:
        (derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH,
         export_json.ROOT) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_citation_sources:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
