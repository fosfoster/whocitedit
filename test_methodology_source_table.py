#!/usr/bin/env python3
"""The /methodology SOURCES table must list exactly render.py's recognised
citation-edge indexes -- no fewer (a silently-undeclared index) and no more
or duplicated (Crossref living in both citation_sources and metadata_sources).

Whole-set property, not one source at a time: every key in
render.CITATION_SOURCE_NAMES has a declaration in the exported
citation_sources, each declaration's name matches the reader-facing name
render.py uses for that key, and render_methodology() emits exactly one
SOURCES row per declared source.
"""
import json
import re
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


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
             render.DATA, render.SITE, render.ASSETS)
    try:
        db_path = tmp / "methodology.db"
        conn = build_corpus(db_path)
        conn.close()

        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "synthetic export failed")

        corpus = json.loads((export_json.OUT / "corpus.json").read_text())
        declarations = corpus.get("citation_sources", {})

        # Every recognised citation-edge index has a declaration whose name
        # matches the reader-facing name render.py uses for it.
        for key, reader_name in render.CITATION_SOURCE_NAMES.items():
            bad += check(
                key in declarations,
                f"{key!r} is a recognised citation-edge index with no exported declaration",
            )
            if key in declarations:
                # Containment rather than exact equality: a declaration may
                # carry a fuller formal name (e.g. "OpenCitations COCI") than
                # the short label render.py uses in prose and edge-status
                # labels ("OpenCitations", pinned by test_crossref_edge_render.py),
                # but it must still visibly be the same source.
                bad += check(
                    reader_name in declarations[key].get("name", ""),
                    f"declared name for {key!r} is {declarations[key].get('name')!r}, "
                    f"which does not name render.py's {reader_name!r}",
                )

        html = render.render_methodology(corpus)

        # Pull just the rows out of the SOURCES table, not the whole page.
        panel_match = re.search(
            r"<h2>Sources</h2>.*?<tbody>(.*?)</tbody>", html, re.DOTALL
        )
        bad += check(panel_match is not None, "could not find the Sources table in the rendered page")
        table_body = panel_match.group(1) if panel_match else ""
        row_names = re.findall(r"<tr><td>(.*?)</td>", table_body)

        # Exactly one row per declared source, naming its url, licence and role.
        bad += check(
            len(row_names) == len(declarations),
            f"rendered {len(row_names)} SOURCES rows but {len(declarations)} sources are declared",
        )
        bad += check(
            len(row_names) == len(set(row_names)),
            f"a source name is rendered more than once in the SOURCES table: {row_names}",
        )

        for key, source in declarations.items():
            bad += check(
                source["name"] in row_names,
                f"{source['name']!r} ({key}) is declared but has no row in the rendered SOURCES table",
            )
            bad += check(
                source["url"] in table_body and source["license"] in table_body
                and source["role"] in table_body,
                f"the rendered row for {source['name']!r} is missing its url, licence or role",
            )

        # Crossref must not be double-rendered via metadata_sources -- only
        # citation_sources feeds the SOURCES table.
        metadata_names = {s["name"] for s in (corpus.get("metadata_sources") or {}).values()}
        citation_names = {s["name"] for s in declarations.values()}
        overlap = metadata_names & citation_names
        bad += check(
            "crossref" in declarations,
            "crossref should be declared as a citation source (t1)",
        )
        bad += check(
            bool(overlap),
            "expected Crossref to be named in both citation_sources and metadata_sources",
        )
        for name in overlap:
            bad += check(
                row_names.count(name) == 1,
                f"{name!r} appears in both citation_sources and metadata_sources but is "
                f"rendered {row_names.count(name)} times in the SOURCES table",
            )
    finally:
        (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
         render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_methodology_source_table:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
