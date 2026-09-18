#!/usr/bin/env python3
"""export_json.main() must ship a citation_edge_coverage aggregation over the
citation table's `sources` column, bucketing edges by how many distinct
indexes assert them.

Builds a synthetic corpus, drives its citation.sources values to a fixed
distribution, and asserts the exported totals against counts computed
independently from that fixture -- not against whatever the implementation
happens to produce.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import export_json
from test_pipeline import build_corpus


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (export_json.OUT, export_json.DB_PATH, export_json.ROOT)
    try:
        db_path = tmp / "coverage.db"
        conn = build_corpus(db_path)

        # build_corpus seeds (W2,W1), (W3,W1), (W3,W2), each defaulting to
        # ["openalex"]. Add the reverse pairs so there are enough edges to
        # cover the whole fixed distribution plus a "the rest" bucket.
        for citing, cited in [("W1", "W2"), ("W1", "W3"), ("W2", "W3")]:
            conn.execute(
                "INSERT INTO citation(citing_id,cited_id) VALUES(?,?)", (citing, cited)
            )

        fixture = {
            ("W2", "W1"): ["openalex", "opencitations"],
            ("W3", "W1"): ["openalex", "opencitations"],
            ("W3", "W2"): ["openalex", "opencitations", "crossref"],
            ("W1", "W2"): ["crossref"],
            ("W1", "W3"): ["opencitations"],
            # ("W2", "W3") left at the schema default ["openalex"].
        }
        for (citing, cited), sources in fixture.items():
            conn.execute(
                "UPDATE citation SET sources = ? WHERE citing_id = ? AND cited_id = ?",
                (json.dumps(sources), citing, cited),
            )
        conn.commit()

        rows = conn.execute("SELECT sources FROM citation").fetchall()
        expected_by_index_count: dict[int, int] = {}
        expected_single_index: dict[str, int] = {}
        for row in rows:
            edge_sources = json.loads(row["sources"])
            n = len(edge_sources)
            expected_by_index_count[n] = expected_by_index_count.get(n, 0) + 1
            if n == 1:
                source_id = edge_sources[0]
                expected_single_index[source_id] = expected_single_index.get(source_id, 0) + 1
        expected_total = len(rows)
        conn.close()

        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "synthetic export failed")

        corpus = json.loads((export_json.OUT / "corpus.json").read_text())
        coverage = corpus.get("citation_edge_coverage")
        bad += check(coverage is not None, "citation_edge_coverage is absent from corpus.json")
        coverage = coverage or {}

        bad += check(
            coverage.get("total") == expected_total,
            f"total is {coverage.get('total')!r}, expected {expected_total}",
        )
        bad += check(
            coverage.get("total") == corpus.get("counts", {}).get("citations"),
            f"citation_edge_coverage.total ({coverage.get('total')!r}) does not equal "
            f"counts.citations ({corpus.get('counts', {}).get('citations')!r})",
        )

        expected_by_index_count_str = {str(n): c for n, c in expected_by_index_count.items()}
        bad += check(
            coverage.get("by_index_count") == expected_by_index_count_str,
            f"by_index_count is {coverage.get('by_index_count')!r}, "
            f"expected {expected_by_index_count_str!r}",
        )
        bad += check(
            coverage.get("single_index") == expected_single_index,
            f"single_index is {coverage.get('single_index')!r}, "
            f"expected {expected_single_index!r}",
        )
    finally:
        (export_json.OUT, export_json.DB_PATH, export_json.ROOT) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_citation_edge_coverage:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
