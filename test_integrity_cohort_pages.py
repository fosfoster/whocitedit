#!/usr/bin/env python3
"""Offline coverage for uncapped, overlapping work-integrity cohorts."""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import render
import test_full_corpus_render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


SIGNALS = ("title", "authors", "doi_year", "references")


def evidence_for(weak_signals):
    weak_signals = set(weak_signals)
    return [
        {
            "signal": signal,
            "direction": "weakens" if signal in weak_signals else "supports",
            "value": None,
        }
        for signal in SIGNALS
    ]


def work_detail(row, weak_signals):
    return {
        "id": row["id"], "title": row["title"],
        "quality": {"band": "partial", "sentence": "Synthetic fixture.",
                    "evidence": evidence_for(weak_signals)},
        "authors": [], "abstract": {"text": "", "reason": "not-in-source"},
        "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
        "topics": [], "doi": None, "oa": {"license": None, "url": None},
        "openalex_url": "", "year": 2020, "source": {"name": ""},
        "cited_by_count": row["cited"], "in_corpus_cited_by": 0, "raw": "",
    }


def write_fixture(data: Path):
    # Every member of this large group belongs to all four cohorts.  This proves
    # each cohort is uncapped and that a work can be retained in overlapping
    # honesty-layer views rather than assigned to only one of them.
    overlapping = [
        {"id": f"W-ALL-{number:03d}", "title": f"Overlapping work {number:03d}",
         "cited": number, "in_corpus_cited": 0}
        for number in range(401)
    ]
    title_only = {
        "id": "W-TITLE-ONLY", "title": "", "cited": 1,
        "in_corpus_cited": 0,
    }
    clean = {
        "id": "W-CLEAN", "title": "Clean work", "cited": 1,
        "in_corpus_cited": 0,
    }
    works = [clean, overlapping[0], title_only, *overlapping[1:]]
    weak_signals = {
        **{row["id"]: SIGNALS for row in overlapping},
        title_only["id"]: ("title",),
        clean["id"]: (),
    }
    for row in works:
        row.update(authors=[], n_authors=0, quality="partial", year=2020)

    corpus = {
        "counts": {"works": len(works), "authors": 0, "citations": 0,
                   "coauthor_edges": 0, "institutions": 0},
        "identity": {"high": 0, "medium": 0, "low": 0},
        "quality": {"complete": 0, "partial": len(works), "suspect": 0},
        "definition": {"name": "Synthetic integrity cohort", "description": "Fixture corpus."},
        "abstracts": {}, "sources": [], "identity_notes": {},
        "identity_bands": {"high": "High.", "medium": "Medium.", "low": "Low."},
        "quality_notes": {},
    }
    (data / "authors").mkdir(parents=True)
    (data / "works").mkdir()
    (data / "corpus.json").write_text(json.dumps(corpus))
    (data / "authors-index.json").write_text("[]")
    (data / "works-index.json").write_text(json.dumps(works))
    (data / "payloads.json").write_text("{}")
    (data / "authors" / "fixture.json").write_text("{}")
    (data / "works" / "fixture.json").write_text(
        json.dumps({
            row["id"]: work_detail(row, weak_signals[row["id"]])
            for row in works
        })
    )
    return works, weak_signals


def cohort_ids(page):
    return re.findall(r'href="\.\./\.\./w/([^/"]+)/"', page)


def main() -> int:
    bad = 0
    temporary = Path(tempfile.mkdtemp())
    saved = render.DATA, render.SITE, render.ASSETS
    try:
        data = temporary / "data"
        works, weak_signals = write_fixture(data)
        render.DATA = data
        render.SITE = temporary / "site"
        render.ASSETS = Path(__file__).parent / "web" / "assets"
        bad += check(render.main() == 0, "synthetic render failed")

        sitemap = (render.SITE / "sitemap.xml").read_text()
        cohorts = {
            "title": ("works/missing-title", "list no title at all"),
            "authors": ("works/missing-authors", "list no authors at all"),
            "doi_year": (
                "works/doi-year-disagreement",
                "publication year that disagrees with the year asserted by their DOI",
            ),
            "references": ("works/heavily-cited-no-references", "list no references at all"),
        }
        rendered_members = {}
        for signal, (route, defect) in cohorts.items():
            expected = [row["id"] for row in works if signal in weak_signals[row["id"]]]
            page = render.SITE / route / "index.html"
            bad += check(page.exists(), f"missing /{route}/")
            if not page.exists():
                continue
            rendered = page.read_text()
            rendered_members[signal] = cohort_ids(rendered)
            bad += check(rendered_members[signal] == expected,
                         f"/{route}/ membership or works-index order is wrong")
            bad += check(f"{len(expected):,}" in rendered,
                         f"/{route}/ does not display its exact cohort total")
            bad += check(defect in rendered,
                         f"/{route}/ does not describe its concrete source defect")
            bad += check(rendered.count("<tbody>") == 1 and rendered.count("<tr>") == len(expected) + 1,
                         f"/{route}/ does not statically render every cohort row")
            for work_id in expected:
                bad += check((render.SITE / "w" / work_id / "index.html").exists(),
                             f"/{route}/ links missing work page for {work_id}")
            bad += check(f"/{route}/" in sitemap, f"/{route}/ missing from sitemap")
            bad += check(f"{route}/index.html" in test_full_corpus_render.FIXED_HTML_ROUTES,
                         f"/{route}/ missing from FIXED_HTML_ROUTES")
            bad += check(len(expected) > 400, f"/{route}/ fixture does not exceed browse cap")

        shared_id = "W-ALL-000"
        bad += check(all(shared_id in rendered_members[signal] for signal in SIGNALS),
                     "one work does not appear in every applicable cohort page")
    finally:
        render.DATA, render.SITE, render.ASSETS = saved
        shutil.rmtree(temporary, ignore_errors=True)

    print("test_integrity_cohort_pages:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
