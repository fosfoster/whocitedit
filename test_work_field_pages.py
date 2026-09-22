#!/usr/bin/env python3
"""End-to-end static-build coverage for work-page field memberships.

Builds full temporary sites for a modern multi-field export and a legacy
export with neither fields-index.json nor per-work fields arrays, then checks
every generated canonical work page and every membership target.
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
    payload = {
        "id": work["id"], "title": work["title"], "authors": [],
        "quality": {"band": work["quality"], "sentence": "Synthetic record.", "evidence": []},
        "abstract": {"text": "", "reason": "not-in-source"},
        "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
        "topics": [], "doi": None, "oa": {"license": None, "url": None},
        "openalex_url": "", "year": work["year"], "source": {"name": ""},
        "cited_by_count": work["cited"], "in_corpus_cited_by": work["in_corpus_cited"],
        "raw": "", "type": "article", "date": None,
    }
    if "fields" in work:
        payload["fields"] = list(work["fields"])
    return payload


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
        "quality": {
            "complete": sum(work["quality"] == "complete" for work in works),
            "partial": sum(work["quality"] == "partial" for work in works),
            "suspect": sum(work["quality"] == "suspect" for work in works),
        },
        "abstracts": {}, "sources": [], "identity_notes": {},
        "identity_bands": {"high": "", "medium": "", "low": ""},
        "quality_notes": {},
    }
    if fields is not None:
        corpus["fields"] = {
            field["key"]: {"name": field["name"], "description": field["description"]}
            for field in fields
        }
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


def membership_hrefs(page):
    sections = re.findall(
        r'<section class="field-memberships" aria-labelledby="field-memberships-heading">'
        r'(.*?)</section>',
        page,
        re.S,
    )
    if not sections:
        return sections, []
    return sections, re.findall(r'<a href="([^"]+)">', sections[0])


def rendered_work_ids(site: Path):
    return sorted(
        path.parent.name
        for path in (site / "w").glob("*/index.html")
    )


def check_work_pages(site: Path, works, expected):
    bad = check(
        rendered_work_ids(site) == sorted(work["id"] for work in works),
        "static build did not preserve the canonical work output paths",
    )
    for work in works:
        wid = work["id"]
        page = site / "w" / wid / "index.html"
        if not page.exists():
            bad += check(False, f"missing /w/{wid}/")
            continue
        page_html = page.read_text()
        sections, hrefs = membership_hrefs(page_html)
        bad += check(len(sections) == 1,
                     f"/w/{wid}/ has {len(sections)} membership sections, expected one")
        bad += check(hrefs == expected[wid],
                     f"/w/{wid}/ memberships are {hrefs}, expected {expected[wid]}")
        bad += check(
            f'<link rel="canonical" href="https://whocitedit.com/w/{wid}">' in page_html,
            f"field memberships changed the canonical work URL for {wid}",
        )
        for href in hrefs:
            target = (page.parent / href / "index.html").resolve()
            bad += check(target.exists(),
                         f"/w/{wid}/ membership href {href} does not resolve to a field page")
    return bad


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (render.DATA, render.SITE, render.ASSETS, getattr(render, "NAV_FIELDS", []))
    try:
        render.ASSETS = Path(__file__).parent / "web" / "assets"

        # Modern exports own their memberships.  The overlapping work gets
        # both links; each single-field work gets only its declared link.
        fields = base_fields()
        works = base_works()
        modern_data = tmp / "modern-data"
        write_fixture(modern_data, works, fields=fields)
        render.DATA = modern_data
        render.SITE = tmp / "modern-site"
        bad += check(render.main() == 0, "modern multi-field render failed")

        modern_expected = {
            work["id"]: [f"../../fields/{key}/" for key in work["fields"]]
            for work in works
        }
        bad += check_work_pages(render.SITE, works, modern_expected)

        # Legacy exports have no field surface on either the index or shard.
        # render.main() establishes one normalized field for every work page.
        legacy_definition = {"name": "Legacy Fixture Field", "description": "One old field."}
        legacy_works = [{key: value for key, value in work.items() if key != "fields"}
                        for work in works]
        legacy_data = tmp / "legacy-data"
        write_fixture(legacy_data, legacy_works, definition=legacy_definition)
        legacy_key = corpus_contract.field_key(legacy_definition["name"])
        bad += check(
            not (legacy_data / "fields-index.json").exists()
            and all("fields" not in work for work in json.loads(
                (legacy_data / "works-index.json").read_text()))
            and all("fields" not in work for work in json.loads(
                (legacy_data / "works" / "fixture.json").read_text()).values()),
            "legacy fixture unexpectedly contains a field export surface",
        )

        render.DATA = legacy_data
        render.SITE = tmp / "legacy-site"
        bad += check(render.main() == 0, "legacy render without field exports failed")

        legacy_expected = {
            work["id"]: [f"../../fields/{legacy_key}/"] for work in legacy_works
        }
        bad += check_work_pages(render.SITE, legacy_works, legacy_expected)
        bad += check(
            (render.SITE / "fields" / legacy_key / "index.html").exists(),
            f"legacy normalized field route /fields/{legacy_key}/ is missing",
        )
    finally:
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_work_field_pages:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
