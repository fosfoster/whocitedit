#!/usr/bin/env python3
"""Citation graph assertions retain their source payloads in exported JSON."""
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
FIXTURES = {
    "openalex": ("openalex/citation-sources.json", "fixture://openalex/citation-sources"),
    "opencitations": ("opencitations/references.json", "fixture://opencitations/references"),
    "europepmc_search": ("europepmc/search.json", "fixture://europepmc/search"),
    "europepmc": ("europepmc/references.json", "fixture://europepmc/references"),
    "crossref": ("crossref/work-references.json", "fixture://crossref/work-references"),
    "arxiv": ("arxiv/query.json", "fixture://arxiv/query"),
    "semanticscholar": ("semanticscholar/references.json", "fixture://semanticscholar/references"),
}


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
            "fetched_at": "2026-09-21T00:00:00+00:00",
            "path": str(path.relative_to(root)),
        }, sort_keys=True) + "\n")
    return sha


def graph_edges(work: dict) -> dict[tuple[str, str], dict]:
    return {(edge["s"], edge["t"]): edge for edge in work["graph"]["edges"]}


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH,
             export_json.ROOT)
    try:
        for filename, url in FIXTURES.values():
            store_payload(tmp, json.loads((ROOT / "docs" / "fixtures" / filename).read_text()), url)

        derive.RAW = tmp / "raw"
        derive.MANIFEST = tmp / "manifest.jsonl"
        db_path = tmp / "corpus.db"
        conn = db.connect(db_path)
        derive.load(conn)

        # Older manually staged rows have sources but no assertion records.
        # They remain readable, with an explicitly empty assertion array.
        conn.execute(
            "INSERT INTO citation(citing_id, cited_id, sources) VALUES(?,?,?)",
            ("W2", "W3", json.dumps(["legacy"])),
        )
        conn.commit()

        expected_edges = {
            (row["citing_id"], row["cited_id"]): json.loads(row["sources"])
            for row in conn.execute("SELECT citing_id, cited_id, sources FROM citation")
        }
        expected_assertions = {}
        for row in conn.execute(
            "SELECT citing_id, cited_id, source, raw_sha FROM citation_assertion "
            "ORDER BY citing_id, cited_id, source"
        ):
            expected_assertions.setdefault((row["citing_id"], row["cited_id"]), []).append(
                {"source": row["source"], "raw": row["raw_sha"]}
            )
        conn.close()

        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = ROOT
        bad += check(export_json.main() == 0, "synthetic export failed")

        work = json.loads(
            (export_json.OUT / "works" / f"{export_json.shard('W1')}.json").read_text()
        )["W1"]
        edges = graph_edges(work)
        payloads = json.loads((export_json.OUT / "payloads.json").read_text())

        direct = edges.get(("W1", "W2"))
        bad += check(direct is not None, "the six-source direct edge was not exported")
        if direct:
            bad += check(direct["sources"] == expected_edges[("W1", "W2")],
                         "the direct edge's existing sources changed")
            bad += check(direct["assertions"] == expected_assertions[("W1", "W2")],
                         "the direct edge did not export every persisted assertion")
            bad += check(len(direct["assertions"]) == 6,
                         "the direct edge is not corroborated by all six fixture sources")

        inner = edges.get(("W4", "W3"))
        bad += check(inner is not None and inner.get("inner") is True,
                     "the inner-neighbour edge was not exported as inner")
        if inner:
            bad += check(inner["sources"] == expected_edges[("W4", "W3")],
                         "the inner edge's existing sources changed")
            bad += check(inner["assertions"] == expected_assertions[("W4", "W3")],
                         "the inner edge did not export its persisted assertion")

        legacy = edges.get(("W2", "W3"))
        bad += check(legacy is not None and legacy["sources"] == ["legacy"],
                     "the manually staged edge changed endpoints or sources")
        bad += check(legacy is not None and legacy["assertions"] == [],
                     "the manually staged edge without assertions is not exportable")

        for edge in edges.values():
            key = (edge["s"], edge["t"])
            expected = expected_assertions.get(key, [])
            bad += check(edge["sources"] == expected_edges[key],
                         f"{edge['s']} -> {edge['t']} sources changed during export")
            bad += check(edge["assertions"] == expected,
                         f"{edge['s']} -> {edge['t']} assertions differ from the database")
            bad += check(edge["assertions"] == sorted(edge["assertions"], key=lambda item: item["source"]),
                         f"{edge['s']} -> {edge['t']} assertions are not sorted by source")
            bad += check(all(item["source"] in edge["sources"] for item in edge["assertions"]),
                         f"{edge['s']} -> {edge['t']} exported an assertion outside sources")
            if expected:
                bad += check([item["source"] for item in edge["assertions"]] == edge["sources"],
                             f"{edge['s']} -> {edge['t']} does not have one assertion per source")
            bad += check(all(item["raw"] in payloads for item in edge["assertions"]),
                         f"{edge['s']} -> {edge['t']} references a payload absent from payloads.json")

        bad += check(
            {(edge["s"], edge["t"]) for edge in edges.values()}
            == set(expected_edges),
            "export changed the graph edge endpoints",
        )
    finally:
        (derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH,
         export_json.ROOT) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_citation_assertion_export:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
