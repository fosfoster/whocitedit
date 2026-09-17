#!/usr/bin/env python3
"""Focused export-to-render provenance and citation-source contract."""
import json
import shutil
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import export_json
import render
from test_pipeline import build_corpus

DIRECT_SHA = "1" * 64
WORK_SHA = "2" * 64
FALLBACK_SHA = "3" * 64
DIRECT_FETCHED = "2026-09-10T01:02:03+00:00"
WORK_FETCHED = "2026-09-11T04:05:06+00:00"
FALLBACK_FETCHED = "2026-09-12T07:08:09+00:00"


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


def stage_provenance(conn) -> None:
    for sha, url, fetched in (
        (DIRECT_SHA, "https://api.openalex.org/authors/A11", DIRECT_FETCHED),
        (WORK_SHA, "https://api.openalex.org/works/W1", WORK_FETCHED),
        (FALLBACK_SHA, "https://api.openalex.org/works?filter=openalex:W2|W3", FALLBACK_FETCHED),
    ):
        conn.execute(
            "INSERT INTO raw_payload(sha256,url,fetched_at,path) VALUES(?,?,?,?)",
            (sha, url, fetched, f"harvest/raw/{sha[:2]}/{sha}.json"),
        )
    conn.execute("UPDATE work SET raw_sha = ? WHERE id = 'W1'", (WORK_SHA,))
    conn.execute("UPDATE work SET raw_sha = ? WHERE id IN ('W2', 'W3')", (FALLBACK_SHA,))
    conn.execute("UPDATE author SET raw_sha = ? WHERE id IN ('A11', 'A22')", (DIRECT_SHA,))
    conn.execute("UPDATE author SET raw_sha = NULL WHERE id = 'A33'")
    conn.execute(
        "UPDATE citation SET sources = ? WHERE citing_id = 'W2' AND cited_id = 'W1'",
        (json.dumps(["openalex"]),),
    )
    conn.execute(
        "UPDATE citation SET sources = ? WHERE citing_id = 'W3' AND cited_id = 'W1'",
        (json.dumps(["opencitations"]),),
    )
    conn.execute(
        "UPDATE citation SET sources = ? WHERE citing_id = 'W3' AND cited_id = 'W2'",
        (json.dumps(["openalex", "opencitations", "europepmc"]),),
    )
    conn.commit()


class VisibleTableRows(HTMLParser):
    """Collect visible table-row text without counting tag attributes."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[str] = []
        self._parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._parts is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self._parts is not None:
            self.rows.append(" ".join("".join(self._parts).split()))
            self._parts = None


def visible_table_rows(document: str) -> list[str]:
    parser = VisibleTableRows()
    parser.feed(document)
    return parser.rows


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
             render.DATA, render.SITE, render.ASSETS)
    try:
        db_path = tmp / "provenance.db"
        conn = build_corpus(db_path)
        stage_provenance(conn)
        conn.close()

        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "synthetic export failed")

        works = load_shards(export_json.OUT / "works")
        authors = load_shards(export_json.OUT / "authors")
        corpus = json.loads((export_json.OUT / "corpus.json").read_text())
        payloads = json.loads((export_json.OUT / "payloads.json").read_text())

        asserted_sources = {
            source_id
            for work in works.values()
            for edge in work["graph"]["edges"]
            for source_id in edge["sources"]
        }
        declarations = corpus.get("citation_sources", {})
        bad += check(
            asserted_sources == set(declarations) == {"openalex", "opencitations", "europepmc"},
            f"edge sources {sorted(asserted_sources)} do not join exactly to declarations "
            f"{sorted(declarations)}",
        )
        for source_id, source in declarations.items():
            bad += check(source.get("id") == source_id,
                         f"{source_id} declaration has a mismatched machine identifier")
            bad += check(
                all(source.get(field) for field in ("name", "url", "license", "role")),
                f"{source_id} declaration lost reader-facing fields",
            )
            bad += check(
                "citation edges" in source["role"],
                f"{source_id} declaration lost its citation-edge role",
            )

        bad += check(authors["A11"]["raw"] == DIRECT_SHA,
                     "direct author did not export its payload hash")
        bad += check(authors["A33"]["raw"] is None,
                     "fallback author unexpectedly gained direct provenance")
        bad += check(works["W1"]["raw"] == WORK_SHA,
                     "work did not export its payload hash")
        bad += check(payloads[WORK_SHA]["fetched_at"] == WORK_FETCHED,
                     "payload map lost the exported work fetch date")

        render.DATA = export_json.OUT
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "synthetic render failed")

        work_page = (render.SITE / "w" / "W1" / "index.html").read_text()
        direct_author_page = (render.SITE / "a" / "A11" / "index.html").read_text()
        fallback_author_page = (render.SITE / "a" / "A33" / "index.html").read_text()
        methodology = (render.SITE / "methodology" / "index.html").read_text()

        bad += check(f"sha256 {WORK_SHA}" in work_page and WORK_FETCHED in work_page,
                     "work page lacks its complete hash and exported fetch date")
        bad += check(f"sha256 {DIRECT_SHA}" in direct_author_page
                     and DIRECT_FETCHED in direct_author_page,
                     "direct author page lacks its complete hash and exported fetch date")
        bad += check("No direct source payload hash was recorded for this author" in fallback_author_page
                     and "linked exported works" in fallback_author_page,
                     "fallback author page does not explain work-derived provenance")
        bad += check(f"sha256 {FALLBACK_SHA}" in fallback_author_page
                     and FALLBACK_FETCHED in fallback_author_page,
                     "fallback author page does not resolve through its linked work payload")

        bad += check("OpenAlex only" in work_page,
                     "OpenAlex-only citation evidence is not disclosed")
        bad += check("OpenCitations only" in work_page
                     and "unconfirmed by OpenAlex" in work_page,
                     "OpenCitations-only citation evidence is not disclosed")
        bad += check("independently assert the same directed DOI-resolved edge" in methodology,
                     "citation corroboration methodology is missing")
        methodology_rows = visible_table_rows(methodology)
        for source_id, source in declarations.items():
            matching_rows = [row for row in methodology_rows if source["name"] in row]
            bad += check(
                any(source["url"] in row for row in matching_rows),
                f"methodology does not visibly disclose the URL for {source_id}",
            )
            bad += check(
                any(
                    all(source[field] in row for field in ("name", "url", "license", "role"))
                    for row in matching_rows
                ),
                f"methodology does not visibly disclose every field for {source_id}",
            )
    finally:
        (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
         render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_provenance_contract:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
