#!/usr/bin/env python3
"""End-to-end static-build coverage for work-page field memberships.

Builds full temporary sites (modern multi-field export, and a legacy export
with neither fields-index.json nor per-work fields arrays) and inspects every
generated /w/<work-id>/index.html for its exact field membership links.
"""
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
    d = {
        "id": work["id"], "title": work["title"], "authors": [],
        "quality": {"band": work["quality"], "sentence": "Synthetic record.", "evidence": []},
        "abstract": {"text": "", "reason": "not-in-source"},
        "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
        "topics": [], "doi": None, "oa": {"license": None, "url": None},
        "openalex_url": "", "year": work["year"], "source": {"name": ""},
        "cited_by_count": work["cited"], "in_corpus_cited": work["in_corpus_cited"],
        "in_corpus_cited_by": work["in_corpus_cited"],
        "raw": "", "type": "article", "date": None,
    }
    if "fields" in work:
        d["fields"] = work["fields"]
    return d


def base_works():
    return [
        {"id": "W-both", "title": "Overlapping paper", "authors": [], "n_authors": 0,
         "quality": "complete", "year": 2024, "cited": 40, "in_corpus_cited": 2,
         "fields": ["alpha", "zeta"]},
        {"id": "W-alpha", "title": "Alpha-only paper", "authors": [], "n_authors": 0,
         "quality": "partial", "year": 2023, "cited": 30, "in_corpus_cited": 1,
         "fields": ["alpha"]},
        {"id": "W-zeta", "title": "Zeta-only paper", "authors": [], "n_authors": 0,
         "quality": "complete", "year": 2021, "cited": 10, "in_corpus_cited": 0,
         "fields": ["zeta"]},
    ]


def base_fields():
    return [
        {"key": "alpha", "name": "Alpha Field", "description": "Alpha papers.", "works": 2},
        {"key": "zeta", "name": "Zeta Field", "description": None, "works": 2},
    ]


def write_fixture(data: Path, works, fields=None, definition=None):
    corpus = {
        "definition": definition or {"name": "Synthetic corpus", "description": "Fixture corpus."},
        "counts": {"works": len(works), "authors": 0, "citations": 0,
                   "coauthor_edges": 0, "institutions": 0},
        "identity": {"high": 0, "medium": 0, "low": 0},
        "quality": {"complete": 2, "partial": 1, "suspect": 0},
        "abstracts": {}, "sources": [], "identity_notes": {},
        "identity_bands": {"high": "", "medium": "", "low": ""},
        "quality_notes": {},
    }
    if fields is not None:
        corpus["fields"] = {f["key"]: {"name": f["name"], "description": f["description"]} for f in fields}
    (data / "works").mkdir(parents=True)
    (data / "authors").mkdir()
    (data / "corpus.json").write_text(json.dumps(corpus))
    (data / "works-index.json").write_text(json.dumps(works))
    if fields is not None:
        (data / "fields-index.json").write_text(json.dumps(fields))
    (data / "authors-index.json").write_text("[]")
    (data / "payloads.json").write_text("{}")
    (data / "works" / "fixture.json").write_text(json.dumps({
        work["id"]: detail(work) for work in works
    }))
    (data / "authors" / "fixture.json").write_text("{}")


def membership_hrefs(html):
    section = re.search(
        r'<section class="field-memberships" aria-labelledby="field-memberships-heading">(.*?)</section>',
        html, re.S,
    )
    if not section:
        return []
    return re.findall(r'<a href="([^"]+)">', section.group(1))


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (render.DATA, render.SITE, render.ASSETS, getattr(render, "NAV_FIELDS", []))
    try:
        # --- Modern export: overlapping and single-field works keep their
        # exact declared memberships, and only those.
        fields = base_fields()
        works = base_works()
        data = tmp / "modern-data"
        write_fixture(data, works, fields=fields)
        render.DATA = data
        render.SITE = tmp / "modern-site"
        render.ASSETS = Path(__file__).parent / "web" / "assets"
        bad += check(render.main() == 0, "modern multi-field render failed")

        site = render.SITE
        expected = {
            "W-both": {"../../fields/alpha/", "../../fields/zeta/"},
            "W-alpha": {"../../fields/alpha/"},
            "W-zeta": {"../../fields/zeta/"},
        }
        for work in works:
            page = site / "w" / work["id"] / "index.html"
            bad += check(page.exists(), f"missing /w/{work['id']}/")
            if not page.exists():
                continue
            hrefs = set(membership_hrefs(page.read_text()))
            bad += check(hrefs == expected[work["id"]],
                         f"/w/{work['id']}/ memberships are {hrefs}, expected {expected[work['id']]}")
        for field in fields:
            bad += check((site / "fields" / field["key"] / "index.html").exists(),
                         f"membership href target /fields/{field['key']}/ was not built")
        for work in works:
            page = site / "w" / work["id"] / "index.html"
            hrefs = membership_hrefs(page.read_text())
            for href in hrefs:
                target = (page.parent / href / "index.html").resolve()
                bad += check(target.exists(),
                             f"/w/{work['id']}/ membership href {href} does not resolve to an existing page")

        # --- Legacy export: no fields-index.json and no per-work fields
        # arrays anywhere (works-index.json nor the work payload shards).
        # Every canonical work page must get exactly the normalized sole field.
        legacy_definition = {"name": "Legacy Fixture Field", "description": "One old field."}
        legacy_works = [{k: v for k, v in work.items() if k != "fields"} for work in works]
        legacy_data = tmp / "legacy-data"
        write_fixture(legacy_data, legacy_works, fields=None, definition=legacy_definition)
        legacy_key = corpus_contract.field_key(legacy_definition["name"])

        render.DATA = legacy_data
        render.SITE = tmp / "legacy-site"
        bad += check(render.main() == 0, "legacy render without field exports failed")

        legacy_site = render.SITE
        legacy_field_page = legacy_site / "fields" / legacy_key / "index.html"
        bad += check(legacy_field_page.exists(), "legacy normalized field route is missing")
        for work in legacy_works:
            page = legacy_site / "w" / work["id"] / "index.html"
            bad += check(page.exists(), f"missing legacy /w/{work['id']}/")
            if not page.exists():
                continue
            hrefs = membership_hrefs(page.read_text())
            bad += check(hrefs == [f"../../fields/{legacy_key}/"],
                         f"legacy /w/{work['id']}/ memberships are {hrefs}, expected the sole normalized field")
            target = (page.parent / hrefs[0] / "index.html").resolve() if hrefs else None
            bad += check(target is not None and target.exists(),
                         f"legacy /w/{work['id']}/ membership href does not resolve to an existing field page")
            bad += check(
                f'<link rel="canonical" href="https://whocitedit.com/w/{work["id"]}">' in page.read_text(),
                f"legacy field memberships changed the canonical work URL for {work['id']}",
            )
    finally:
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_work_field_pages:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
