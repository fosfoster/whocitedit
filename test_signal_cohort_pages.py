#!/usr/bin/env python3
"""Offline coverage for the four per-signal static uncertainty cohorts."""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import render
import test_full_corpus_render


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


SIGNALS = ("title", "authors", "doi_year", "references")


def evidence_for(row):
    """One evidence entry per signal; 'weakens' iff the row names that signal."""
    weak = set(row["weak_signals"])
    return [
        {"signal": signal, "direction": "weakens" if signal in weak else "supports", "value": None}
        for signal in SIGNALS
    ]


def work_detail(row):
    return {
        "id": row["id"], "title": row["title"],
        "quality": {"band": "partial", "sentence": "Synthetic fixture.",
                    "evidence": evidence_for(row)},
        "authors": [], "abstract": {"text": "", "reason": "not-in-source"},
        "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
        "topics": [], "doi": None, "oa": {"license": None, "url": None},
        "openalex_url": "", "year": 2020, "source": {"name": ""},
        "cited_by_count": row["cited"], "in_corpus_cited_by": 0, "raw": "",
    }


def write_fixture(data: Path):
    # 'authors' gets over 400 weakening members to prove the page is uncapped;
    # the other three signals get a handful of weakening members mixed with
    # non-weakening ones, to prove membership filters on direction, not signal presence.
    many_authors = [
        {"id": f"W-AUTH-{n:03d}", "title": f"No-author work {n:03d}", "cited": n,
         "in_corpus_cited": 0, "weak_signals": ["authors"]}
        for n in range(401)
    ]
    clean = [
        {"id": f"W-CLEAN-{n:03d}", "title": f"Clean work {n:03d}", "cited": n,
         "in_corpus_cited": 0, "weak_signals": []}
        for n in range(3)
    ]
    title = [
        {"id": "W-TITLE-1", "title": "", "cited": 1, "in_corpus_cited": 0, "weak_signals": ["title"]},
    ]
    doi_year = [
        {"id": "W-DOIYEAR-1", "title": "DOI year mismatch work", "cited": 1, "in_corpus_cited": 0,
         "weak_signals": ["doi_year"]},
    ]
    references = [
        {"id": "W-REF-1", "title": "No references work", "cited": 1, "in_corpus_cited": 0,
         "weak_signals": ["references"]},
    ]
    works = [
        clean[0], *many_authors[:150], title[0], *many_authors[150:300],
        doi_year[0], references[0], clean[1], *many_authors[300:], clean[2],
    ]
    for row in works:
        row["authors"] = []
        row["n_authors"] = 0
        row["quality"] = "partial"
        row["year"] = 2020

    corpus = {
        "counts": {"works": len(works), "authors": 0, "citations": 0,
                   "coauthor_edges": 0, "institutions": 0},
        "identity": {"high": 0, "medium": 0, "low": 0},
        "quality": {"complete": 0, "partial": len(works), "suspect": 0},
        "definition": {"name": "Synthetic signal cohort", "description": "Fixture corpus."},
        "abstracts": {}, "sources": [], "identity_notes": {},
        "identity_bands": {"high": "High.", "medium": "Medium.", "low": "Low."},
        "quality_notes": {},
    }
    (data / "authors").mkdir(parents=True)
    (data / "works").mkdir()
    (data / "corpus.json").write_text(json.dumps(corpus))
    (data / "authors-index.json").write_text(json.dumps([]))
    (data / "works-index.json").write_text(json.dumps(works))
    (data / "payloads.json").write_text("{}")
    (data / "authors" / "fixture.json").write_text(json.dumps({}))
    (data / "works" / "fixture.json").write_text(
        json.dumps({row["id"]: work_detail(row) for row in works})
    )
    return works


def cohort_ids(html):
    return re.findall(r'href="\.\./\.\./w/([^/"]+)/"', html)


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (render.DATA, render.SITE, render.ASSETS)
    try:
        data = tmp / "data"
        works = write_fixture(data)
        render.DATA = data
        render.SITE = tmp / "site"
        render.ASSETS = Path(__file__).parent / "web" / "assets"
        bad += check(render.main() == 0, "synthetic render failed")

        sitemap = (render.SITE / "sitemap.xml").read_text()
        routes = {
            "title": "works/missing-title",
            "authors": "works/missing-authors",
            "doi_year": "works/doi-year-mismatch",
            "references": "works/no-references",
        }
        for signal, route in routes.items():
            expected = [
                row["id"] for row in works if signal in row["weak_signals"]
            ]
            page = render.SITE / route / "index.html"
            bad += check(page.exists(), f"missing /{route}/")
            if not page.exists():
                continue
            html = page.read_text()
            bad += check(cohort_ids(html) == expected,
                         f"/{route}/ membership or index ordering is wrong")
            bad += check(f"{len(expected):,}" in html,
                         f"/{route}/ does not display its filtered total")
            bad += check(html.count("<tbody>") == 1 and html.count("<tr>") == len(expected) + 1,
                         f"/{route}/ does not statically render every cohort row")
            for ident in expected:
                detail = render.SITE / "w" / ident / "index.html"
                bad += check(detail.exists(), f"/{route}/ links missing w/{ident} detail page")
            bad += check(f"/{route}/" in sitemap, f"/{route}/ missing from sitemap")
            bad += check(f"{route}/index.html" in test_full_corpus_render.FIXED_HTML_ROUTES,
                         f"/{route}/ missing from FIXED_HTML_ROUTES")

        authors_members = [row["id"] for row in works if "authors" in row["weak_signals"]]
        bad += check(len(authors_members) > 400, "authors fixture does not exceed browse preview")
    finally:
        render.DATA, render.SITE, render.ASSETS = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_signal_cohort_pages:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
