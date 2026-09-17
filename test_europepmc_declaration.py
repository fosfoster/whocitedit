#!/usr/bin/env python3
"""Europe PMC citation-source declaration and its multi-index edge labels."""
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


def load_shards(directory: Path) -> dict:
    rows = {}
    for path in sorted(directory.glob("*.json")):
        rows.update(json.loads(path.read_text()))
    return rows


def stage_sources(conn) -> None:
    # W2 -> W1: Europe PMC is the only index asserting this edge.
    conn.execute(
        "UPDATE citation SET sources = ? WHERE citing_id = 'W2' AND cited_id = 'W1'",
        (json.dumps(["europepmc"]),),
    )
    # W3 -> W2: all three indexes assert this edge.
    conn.execute(
        "UPDATE citation SET sources = ? WHERE citing_id = 'W3' AND cited_id = 'W2'",
        (json.dumps(["europepmc", "openalex", "opencitations"]),),
    )
    conn.commit()


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
             render.DATA, render.SITE, render.ASSETS)
    try:
        db_path = tmp / "europepmc.db"
        conn = build_corpus(db_path)
        stage_sources(conn)
        conn.close()

        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "synthetic export failed")

        corpus = json.loads((export_json.OUT / "corpus.json").read_text())
        declarations = corpus.get("citation_sources", {})

        bad += check("europepmc" in declarations, "europepmc is not declared as a citation source")
        source = declarations.get("europepmc", {})
        bad += check(source.get("id") == "europepmc",
                     "europepmc declaration has a mismatched machine identifier")
        bad += check(
            all(source.get(field) for field in ("name", "url", "license", "role")),
            "europepmc declaration is missing a required reader-facing field",
        )
        bad += check("citation edges" in source.get("role", ""),
                     "europepmc declaration lost its citation-edge role")

        render.DATA = export_json.OUT
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "synthetic render failed")

        work_page = (render.SITE / "w" / "W2" / "index.html").read_text()

        bad += check(
            "Europe PMC only" in work_page,
            "the Europe-PMC-only edge is not given its own explicit status",
        )
        bad += check(
            "legacy" not in work_page.lower() or "Legacy edge" not in work_page,
            "the Europe-PMC-only edge fell back to the legacy status",
        )
        bad += check(
            "Corroborated" in work_page
            and "OpenAlex" in work_page
            and "OpenCitations" in work_page
            and "Europe PMC" in work_page,
            "the three-index edge does not name all three corroborating indexes",
        )

        status, label = render.citation_edge_status(
            {"sources": ["europepmc", "openalex", "opencitations"]}
        )
        bad += check(status == "corroborated", "three-index edge is not marked corroborated")
        bad += check(
            all(name in label for name in ("OpenAlex", "OpenCitations", "Europe PMC")),
            f"three-index corroborated label {label!r} does not name all three indexes",
        )

        status, label = render.citation_edge_status({"sources": ["europepmc"]})
        bad += check(status == "europepmc-only", "europepmc-only edge is not given its own status")
        bad += check(status != "legacy", "europepmc-only edge fell back to legacy")
        bad += check("Europe PMC" in label, "europepmc-only label does not name Europe PMC")
    finally:
        (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
         render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_europepmc_declaration:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
