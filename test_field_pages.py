#!/usr/bin/env python3
"""Offline coverage for static field directories and complete field pages."""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import corpus_contract
import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def detail(work):
    return {
        "id": work["id"], "title": work["title"], "authors": [],
        "quality": {"band": work["quality"], "sentence": "Synthetic record.", "evidence": []},
        "abstract": {"text": "", "reason": "not-in-source"},
        "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
        "topics": [], "doi": None, "oa": {"license": None, "url": None},
        "openalex_url": "", "year": work["year"], "source": {"name": ""},
        "cited_by_count": work["cited"], "in_corpus_cited_by": work["in_corpus_cited"],
        "raw": "", "type": "article", "date": None,
    }


def write_fixture(data: Path):
    fields = [
        {"key": "alpha", "name": "Alpha Field", "description": "Alpha papers.", "works": 2},
        {"key": "zeta", "name": "Zeta Field", "description": None, "works": 3},
    ]
    works = [
        {"id": "W-zeta-first", "title": "Zeta first", "authors": [], "n_authors": 0,
         "quality": "complete", "year": 2024, "cited": 40, "in_corpus_cited": 2,
         "fields": ["zeta"]},
        {"id": "W-shared", "title": "Shared paper", "authors": [], "n_authors": 0,
         "quality": "partial", "year": 2023, "cited": 30, "in_corpus_cited": 1,
         "fields": ["alpha", "zeta"]},
        {"id": "W-alpha-last", "title": "Alpha last", "authors": [], "n_authors": 0,
         "quality": "suspect", "year": 2022, "cited": 20, "in_corpus_cited": 0,
         "fields": ["alpha"]},
        {"id": "W-zeta-last", "title": "Zeta last", "authors": [], "n_authors": 0,
         "quality": "complete", "year": 2021, "cited": 10, "in_corpus_cited": 0,
         "fields": ["zeta"]},
    ]
    definitions = {
        "alpha": {"name": "Alpha Field", "description": "Alpha papers."},
        "zeta": {"name": "Zeta Field"},
    }
    corpus = {
        "definition": {"name": "Synthetic multi-field corpus", "description": "Fixture corpus."},
        "fields": definitions,
        "counts": {"works": len(works), "authors": 0, "citations": 0,
                   "coauthor_edges": 0, "institutions": 0},
        "identity": {"high": 0, "medium": 0, "low": 0},
        "quality": {"complete": 2, "partial": 1, "suspect": 1},
        "abstracts": {}, "sources": [], "identity_notes": {},
        "identity_bands": {"high": "", "medium": "", "low": ""},
        "quality_notes": {},
    }
    (data / "works").mkdir(parents=True)
    (data / "authors").mkdir()
    (data / "corpus.json").write_text(json.dumps(corpus))
    (data / "works-index.json").write_text(json.dumps(works))
    (data / "fields-index.json").write_text(json.dumps(fields))
    (data / "authors-index.json").write_text("[]")
    (data / "payloads.json").write_text("{}")
    (data / "works" / "fixture.json").write_text(json.dumps({
        work["id"]: detail(work) for work in works
    }))
    (data / "authors" / "fixture.json").write_text("{}")
    return fields, works, corpus


def member_ids(html):
    table = re.search(r"<tbody>(.*?)</tbody>", html, re.DOTALL)
    return re.findall(r'href="\.\./\.\./w/([^/"]+)/"', table.group(1) if table else "")


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (render.DATA, render.SITE, render.ASSETS, getattr(render, "NAV_FIELDS", []))
    try:
        data = tmp / "data"
        fields, works, corpus = write_fixture(data)
        render.DATA = data
        render.SITE = tmp / "site"
        render.ASSETS = Path(__file__).parent / "web" / "assets"
        bad += check(render.main() == 0, "multi-field synthetic render failed")

        site = render.SITE
        directory = site / "fields" / "index.html"
        bad += check(directory.exists(), "missing /fields/")
        directory_html = directory.read_text() if directory.exists() else ""
        sitemap = (site / "sitemap.xml").read_text()
        expected = {
            field["key"]: [work["id"] for work in works if field["key"] in work["fields"]]
            for field in fields
        }
        for field in fields:
            key = field["key"]
            page = site / "fields" / key / "index.html"
            bad += check(page.exists(), f"missing /fields/{key}/")
            bad += check(f'href="{key}/"' in directory_html,
                         f"field directory does not link {key}")
            bad += check(f'{field["works"]} papers' in directory_html,
                         f"field directory does not render {key}'s exported count")
            if field["description"]:
                bad += check(field["description"] in directory_html,
                             f"field directory does not render {key}'s exported description")
            bad += check(f"/{key}/" in sitemap and f"/fields/{key}/" in sitemap,
                         f"/fields/{key}/ missing from sitemap")
            if not page.exists():
                continue
            html = page.read_text()
            ids = member_ids(html)
            bad += check(ids == expected[key],
                         f"/fields/{key}/ members are not exactly in works-index order: {ids}")
            bad += check(html.count("<tbody>") == 1 and html.count("<tr>") == len(expected[key]) + 1,
                         f"/fields/{key}/ does not statically render every member row")
            for wid in ids:
                bad += check((site / "w" / wid / "index.html").exists(),
                             f"/fields/{key}/ link lacks canonical /w/{wid}/ page")

        bad += check("/fields/" in sitemap, "/fields/ missing from sitemap")
        home = (site / "index.html").read_text()
        papers = (site / "works" / "index.html").read_text()
        for field in fields:
            key, name = field["key"], field["name"]
            bad += check(f'href="./fields/{key}/"' in home and name in home,
                         f"shared navigation does not expose {key}")
            bad += check(f'href="../fields/{key}/"' in papers and name in papers,
                         f"paper-browse navigation does not expose {key}")
        stylesheet = render.ASSETS.joinpath("style.css").read_text()
        bad += check(".field-nav" in stylesheet and ".field-browse-nav" in stylesheet
                     and ".field-nav a:focus-visible" in stylesheet
                     and "@media (max-width: 760px)" in stylesheet,
                     "field navigation lacks responsive, keyboard-visible styling")

        # The committed release has neither new field surface.  Its one legacy
        # field is normalized from the top-level definition and owns all works.
        legacy = tmp / "legacy-data"
        shutil.copytree(data, legacy)
        (legacy / "fields-index.json").unlink()
        legacy_works = json.loads((legacy / "works-index.json").read_text())
        for work in legacy_works:
            work.pop("fields")
        (legacy / "works-index.json").write_text(json.dumps(legacy_works))
        legacy_corpus = dict(corpus)
        legacy_corpus["definition"] = {
            "name": "Legacy Fixture Field", "description": "One old field.",
        }
        legacy_corpus.pop("fields")
        (legacy / "corpus.json").write_text(json.dumps(legacy_corpus))
        legacy_key = corpus_contract.field_key(legacy_corpus["definition"]["name"])
        render.DATA = legacy
        render.SITE = tmp / "legacy-site"
        bad += check(render.main() == 0, "legacy render without field exports failed")
        legacy_page = render.SITE / "fields" / legacy_key / "index.html"
        bad += check(legacy_page.exists(), "legacy normalized field route is missing")
        bad += check(member_ids(legacy_page.read_text() if legacy_page.exists() else "")
                     == [work["id"] for work in works],
                     "legacy field does not contain every work in works-index order")
    finally:
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_field_pages:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
