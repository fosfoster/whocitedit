#!/usr/bin/env python3
"""Crossref citation-edge source declaration and its multi-index edge labels."""
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
    # W2 -> W1: Crossref is the only index asserting this edge.
    conn.execute(
        "UPDATE citation SET sources = ? WHERE citing_id = 'W2' AND cited_id = 'W1'",
        (json.dumps(["crossref"]),),
    )
    # W3 -> W2: all three graph indexes plus Crossref assert this edge.
    conn.execute(
        "UPDATE citation SET sources = ? WHERE citing_id = 'W3' AND cited_id = 'W2'",
        (json.dumps(["crossref", "openalex", "opencitations"]),),
    )
    conn.commit()


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
             render.DATA, render.SITE, render.ASSETS)
    try:
        db_path = tmp / "crossref.db"
        conn = build_corpus(db_path)
        stage_sources(conn)
        conn.close()

        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "synthetic export failed")

        corpus = json.loads((export_json.OUT / "corpus.json").read_text())
        declarations = corpus.get("citation_sources", {})

        bad += check("crossref" in declarations, "crossref is not declared as a citation source")
        source = declarations.get("crossref", {})
        bad += check(source.get("id") == "crossref",
                     "crossref declaration has a mismatched machine identifier")
        bad += check(
            all(source.get(field) for field in ("name", "url", "license", "role")),
            "crossref declaration is missing a required reader-facing field",
        )
        bad += check("citation edges" in source.get("role", ""),
                     "crossref declaration lost its citation-edge role")

        legacy_sources = corpus.get("sources", [])
        bad += check(
            any(entry.get("name") == source.get("name") for entry in legacy_sources),
            "the legacy sources list did not pick up the Crossref row",
        )

        metadata_role = (corpus.get("metadata_sources") or {}).get("crossref", {}).get("role", "")
        bad += check(
            "title" in metadata_role and "date" in metadata_role,
            "Crossref's title/date comparison role in metadata_sources was lost",
        )

        render.DATA = export_json.OUT
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "synthetic render failed")

        work_page = (render.SITE / "w" / "W2" / "index.html").read_text()

        bad += check(
            "Crossref only" in work_page,
            "the Crossref-only edge is not given its own explicit status",
        )
        bad += check(
            "legacy" not in work_page.lower() or "Legacy edge" not in work_page,
            "the Crossref-only edge fell back to the legacy status",
        )
        bad += check(
            "Corroborated" in work_page
            and "OpenAlex" in work_page
            and "OpenCitations" in work_page
            and "Crossref" in work_page,
            "the multi-index edge does not name all three corroborating indexes",
        )

        status, label = render.citation_edge_status(
            {"sources": ["crossref", "openalex", "opencitations"]}
        )
        bad += check(status == "corroborated", "multi-index edge is not marked corroborated")
        bad += check(
            all(name in label for name in ("OpenAlex", "OpenCitations", "Crossref")),
            f"corroborated label {label!r} does not name all three indexes",
        )

        status, label = render.citation_edge_status({"sources": ["crossref"]})
        bad += check(status == "crossref-only", "crossref-only edge is not given its own status")
        bad += check(status != "legacy", "crossref-only edge fell back to legacy")
        bad += check("Crossref" in label, "crossref-only label does not name Crossref")
    finally:
        (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
         render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_crossref_declaration:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
