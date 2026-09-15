#!/usr/bin/env python3
"""Offline coverage for the complete static uncertainty cohorts."""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import render


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def author_detail(row):
    return {
        "id": row["id"], "name": row["name"],
        "confidence": {"band": row["band"], "evidence": []},
        "in_corpus": {"works": row["works"], "hindex": 0},
        "cited_by_count": row["cited"], "works_count": row["works"],
        "orcid": None, "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
        "works": [], "institutions": [], "openalex_url": "",
    }


def work_detail(row):
    return {
        "id": row["id"], "title": row["title"],
        "quality": {"band": row["quality"], "sentence": "Synthetic fixture.", "evidence": []},
        "authors": [], "abstract": {"text": "", "reason": "not-in-source"},
        "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
        "topics": [], "doi": None, "oa": {"license": None, "url": None},
        "openalex_url": "", "year": 2020, "source": {"name": ""},
        "cited_by_count": row["cited"], "in_corpus_cited_by": 0, "raw": "",
    }


def write_fixture(data: Path):
    low = [
        {"id": f"A-LOW-{n:03d}", "name": f"Low author {n:03d}", "band": "low",
         "works": 1, "coauthors": 0, "cited": n}
        for n in range(401)
    ]
    authors = [
        {"id": "A-HIGH", "name": "High author", "band": "high", "works": 1, "coauthors": 0, "cited": 1},
        low[0], *low[1:200],
        {"id": "A-MEDIUM", "name": "Medium author", "band": "medium", "works": 1, "coauthors": 0, "cited": 1},
        *low[200:],
    ]
    partial = [
        {"id": f"W-PARTIAL-{n:03d}", "title": f"Partial work {n:03d}", "authors": [],
         "quality": "partial", "year": 2020, "cited": n, "in_corpus_cited": 0}
        for n in range(401)
    ]
    suspect = [
        {"id": f"W-SUSPECT-{n:03d}", "title": f"Suspect work {n:03d}", "authors": [],
         "quality": "suspect", "year": 2020, "cited": n, "in_corpus_cited": 0}
        for n in range(401)
    ]
    works = [
        {"id": "W-COMPLETE-ONE", "title": "Complete work one", "authors": [],
         "quality": "complete", "year": 2020, "cited": 1, "in_corpus_cited": 0},
        partial[0], suspect[0], *partial[1:200],
        {"id": "W-COMPLETE-TWO", "title": "Complete work two", "authors": [],
         "quality": "complete", "year": 2020, "cited": 1, "in_corpus_cited": 0},
        *suspect[1:200], *partial[200:], *suspect[200:],
    ]
    for row in works:
        row["n_authors"] = len(row["authors"])
    corpus = {
        "counts": {"works": len(works), "authors": len(authors), "citations": 0,
                   "coauthor_edges": 0, "institutions": 0},
        "identity": {"high": 1, "medium": 1, "low": len(low)},
        "quality": {"complete": 2, "partial": len(partial), "suspect": len(suspect)},
        "definition": {"name": "Synthetic cohort", "description": "Fixture corpus."},
        "abstracts": {}, "sources": [], "identity_notes": {},
        "identity_bands": {"high": "High.", "medium": "Medium.", "low": "Low."},
        "quality_notes": {},
    }
    (data / "authors").mkdir(parents=True)
    (data / "works").mkdir()
    (data / "corpus.json").write_text(json.dumps(corpus))
    (data / "authors-index.json").write_text(json.dumps(authors))
    (data / "works-index.json").write_text(json.dumps(works))
    (data / "payloads.json").write_text("{}")
    (data / "authors" / "fixture.json").write_text(
        json.dumps({row["id"]: author_detail(row) for row in authors})
    )
    (data / "works" / "fixture.json").write_text(
        json.dumps({row["id"]: work_detail(row) for row in works})
    )
    return authors, works


def cohort_ids(html, kind):
    return re.findall(rf'href="\.\./\.\./{kind}/([^/"]+)/"', html)


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (render.DATA, render.SITE, render.ASSETS)
    try:
        data = tmp / "data"
        authors, works = write_fixture(data)
        render.DATA = data
        render.SITE = tmp / "site"
        render.ASSETS = Path(__file__).parent / "web" / "assets"
        bad += check(render.main() == 0, "synthetic render failed")

        cohorts = (
            ("authors/low-confidence", authors, "band", "low", "a"),
            ("works/partial", works, "quality", "partial", "w"),
            ("works/suspect", works, "quality", "suspect", "w"),
        )
        sitemap = (render.SITE / "sitemap.xml").read_text()
        for route, index, field, band, kind in cohorts:
            expected = [row["id"] for row in index if row[field] == band]
            page = render.SITE / route / "index.html"
            bad += check(page.exists(), f"missing /{route}/")
            if not page.exists():
                continue
            html = page.read_text()
            bad += check(cohort_ids(html, kind) == expected,
                         f"/{route}/ membership or index ordering is wrong")
            bad += check(f"{len(expected):,} {band}" in html,
                         f"/{route}/ does not display its filtered total")
            bad += check(html.count("<tbody>") == 1 and html.count("<tr>") == len(expected) + 1,
                         f"/{route}/ does not statically render every cohort row")
            for ident in expected:
                detail = render.SITE / kind / ident / "index.html"
                bad += check(detail.exists(), f"/{route}/ links missing {kind}/{ident} detail page")
            bad += check(f"/{route}/" in sitemap, f"/{route}/ missing from sitemap")
            bad += check(len(expected) > 400, f"/{route}/ fixture does not exceed browse preview")
    finally:
        render.DATA, render.SITE, render.ASSETS = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_cohort_pages:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
