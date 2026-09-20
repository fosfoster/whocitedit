#!/usr/bin/env python3
"""Semantic Scholar citation-edge source declaration and its edge labels."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import export_json
import render
from test_pipeline import build_corpus


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def stage_sources(conn) -> None:
    # W2 -> W1: Semantic Scholar is the only index asserting this edge.
    conn.execute(
        "UPDATE citation SET sources = ? WHERE citing_id = 'W2' AND cited_id = 'W1'",
        (json.dumps(["semanticscholar"]),),
    )
    # W3 -> W2: OpenAlex, OpenCitations and Semantic Scholar all assert this edge.
    conn.execute(
        "UPDATE citation SET sources = ? WHERE citing_id = 'W3' AND cited_id = 'W2'",
        (json.dumps(["semanticscholar", "openalex", "opencitations"]),),
    )
    conn.commit()


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
             render.DATA, render.SITE, render.ASSETS)
    try:
        db_path = tmp / "semanticscholar.db"
        conn = build_corpus(db_path)
        stage_sources(conn)
        conn.close()

        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "synthetic export failed")

        corpus = json.loads((export_json.OUT / "corpus.json").read_text())
        declarations = corpus.get("citation_sources", {})

        bad += check("semanticscholar" in declarations,
                     "semanticscholar is not declared as a citation source")
        source = declarations.get("semanticscholar", {})
        bad += check(source.get("id") == "semanticscholar",
                     "semanticscholar declaration has a mismatched machine identifier")
        bad += check(
            all(source.get(field) for field in ("name", "url", "license", "role")),
            "semanticscholar declaration is missing a required reader-facing field",
        )
        bad += check("citation edges" in source.get("role", ""),
                     "semanticscholar declaration lost its citation-edge role")

        legacy_sources = corpus.get("sources", [])
        bad += check(
            any(entry.get("name") == source.get("name") for entry in legacy_sources),
            "the legacy sources list did not pick up the Semantic Scholar row",
        )

        coverage = corpus.get("citation_edge_coverage", {})
        single_index = coverage.get("single_index", {})
        bad += check(
            single_index.get("semanticscholar") == 1,
            f"citation_edge_coverage.single_index did not count the Semantic Scholar-only edge: {single_index}",
        )

        render.DATA = export_json.OUT
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "synthetic render failed")

        work_page = (render.SITE / "w" / "W2" / "index.html").read_text()

        bad += check(
            "Semantic Scholar only" in work_page,
            "the Semantic Scholar-only edge is not given its own explicit status",
        )
        bad += check(
            "legacy" not in work_page.lower() or "Legacy edge" not in work_page,
            "the Semantic Scholar-only edge fell back to the legacy status",
        )

        status, label = render.citation_edge_status({"sources": ["semanticscholar"]})
        bad += check(status == "semanticscholar-only",
                     "semanticscholar-only edge is not given its own status")
        bad += check(status != "legacy", "semanticscholar-only edge fell back to legacy")
        bad += check("Semantic Scholar" in label,
                     "semanticscholar-only label does not name Semantic Scholar")
    finally:
        (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
         render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_semanticscholar_declaration:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
