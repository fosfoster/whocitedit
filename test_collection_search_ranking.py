#!/usr/bin/env python3
"""Coverage for exact-title/name-first ranking in the collection browse search.

There is no JS runtime available in this repo (requirements.txt is deliberately
stdlib-only), so this combines (a) structural assertions on web/assets/app.js
that the ranking helper exists and is actually wired into initCollectionSearch
ahead of the MAX_RESULTS slice, with (b) a data-driven check, using the same
synthetic-corpus pipeline as test_global_search_client.py, that the documented
ordering rule (exact label match ahead of plain substring match, stable within
each tier) is what it takes to keep an exact match inside the first 60 results
of a >60-hit query.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import db
import derive
import export_json
import graph
import render
import test_entity_export

MAX_RESULTS = 60


def check(condition, message):
    if condition:
        return 0
    print(f"  FAIL: {message}")
    return 1


def label(row):
    return row.get("title") or row.get("name") or row["id"]


def normalized(value):
    return str(value or "").lower()


def rank_matches(rows, query, label_for):
    exact = [row for row in rows if normalized(label_for(row)) == query]
    rest = [row for row in rows if normalized(label_for(row)) != query]
    return exact + rest


def build_ranking_corpus(tmp: Path) -> Path:
    """>60 works substring-matching one query, with the exact-title match last."""
    author_id = "A01"
    n_substring_only = 64
    work_payloads = [
        test_entity_export.work(f"W{i}", f"Neural Networks Study {i}", n_substring_only - i, [author_id])
        for i in range(1, n_substring_only + 1)
    ]
    work_payloads.append(test_entity_export.work("WEXACT", "Neural Networks", 0, [author_id]))

    for payload in work_payloads:
        test_entity_export.store_payload(tmp, {"results": [payload]},
                                          f"file://{payload['id'].rsplit('/', 1)[-1]}")

    authors = [{
        "id": f"https://openalex.org/{author_id}",
        "display_name": f"Author {author_id}",
        "works_count": len(work_payloads),
        "cited_by_count": 500,
        "last_known_institutions": [],
    }]
    test_entity_export.store_payload(tmp, {"results": authors}, "file://authors")

    derive.RAW = tmp / "raw"
    derive.MANIFEST = tmp / "manifest.jsonl"
    conn = db.connect(tmp / "corpus.db")
    derive.load(conn)
    graph.build_coauthorship(conn, 2026)
    derive.score_identities(conn)
    conn.commit()
    conn.close()
    return tmp / "corpus.db"


def main() -> int:
    bad = 0

    # -- (a) structural: the helper exists and is wired in ahead of the slice.
    client = (Path(__file__).parent / "web" / "assets" / "app.js").read_text()
    bad += check("function rankMatches(" in client,
                 "app.js lacks a rankMatches ranking helper")

    start = client.find("function initCollectionSearch")
    bad += check(start >= 0, "app.js lacks initCollectionSearch")
    end = client.find("var global = document.querySelector", start)
    block = client[start:end] if start >= 0 and end > start else ""

    render_def = block.find("function render(matches, query)")
    slice_call = block.find("matches.slice(0, MAX_RESULTS)")
    bad += check(render_def >= 0 and slice_call > render_def,
                 "initCollectionSearch lost its render()/MAX_RESULTS slice")

    # The ranked call site: rankMatches must run on the filtered rows and its
    # *result* -- not the bare filtered array -- is what flows into render(),
    # which is what actually reaches the matches.slice(0, MAX_RESULTS) above.
    ranked_call_site = block.find("render(rankMatches(")
    bad += check(ranked_call_site >= 0,
                 "rankMatches's result is not what gets passed into render() before the MAX_RESULTS slice")

    bad += check("render(all.filter(" not in client,
                 "the raw all.filter(...) result is still passed straight to render unranked")

    # -- (b) data-driven: exact match survives the MAX_RESULTS=60 cap.
    tmp = Path(tempfile.mkdtemp())
    saved = (derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH,
             export_json.ROOT, render.DATA, render.SITE, render.ASSETS)
    try:
        db_path = build_ranking_corpus(tmp)
        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "synthetic export failed")

        render.DATA = tmp / "data"
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "synthetic render failed")

        index_path = render.SITE / "data" / "works-index.json"
        bad += check(index_path.exists(), "synthetic render produced no copied works-index.json")
        rows = json.loads(index_path.read_text()) if index_path.exists() else []

        query = normalized("Neural Networks".strip())
        filtered = [row for row in rows if query in normalized(label(row))]
        bad += check(len(filtered) > MAX_RESULTS,
                     f"synthetic index only produced {len(filtered)} substring hits, need > {MAX_RESULTS}")

        exact_rows = [row for row in filtered if normalized(label(row)) == query]
        bad += check(len(exact_rows) == 1, "expected exactly one exact-title match in the fixture")

        if exact_rows:
            exact = exact_rows[0]
            unranked_top = filtered[:MAX_RESULTS]
            bad += check(exact not in unranked_top,
                         "fixture is broken: exact match already survives the cap without ranking")

            ranked = rank_matches(filtered, query, label)
            ranked_top = ranked[:MAX_RESULTS]
            bad += check(exact in ranked_top,
                         "exact-label-first ranking does not keep the exact match inside MAX_RESULTS")

            # Stability: substring-tier rows keep their original filtered order.
            substring_only = [row for row in filtered if row is not exact]
            ranked_substring_only = [row for row in ranked if row is not exact]
            bad += check(substring_only == ranked_substring_only,
                         "ranking reorders rows within the substring tier instead of staying stable")
    finally:
        (derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH,
         export_json.ROOT, render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_collection_search_ranking:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
