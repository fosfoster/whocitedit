#!/usr/bin/env python3
"""Offline coverage for BreadcrumbList JSON-LD on the field directory and pages."""
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


def write_fixture(data: Path):
    fields = [
        {"key": "alpha", "name": "Alpha Field", "description": "Alpha papers.", "works": 1},
        {"key": "zeta", "name": "Zeta Field", "description": None, "works": 1},
    ]
    works = [
        {"id": "W1", "title": "Alpha paper", "authors": [], "n_authors": 0,
         "quality": "complete", "year": 2024, "cited": 10, "in_corpus_cited": 0,
         "fields": ["alpha"]},
        {"id": "W2", "title": "Zeta paper", "authors": [], "n_authors": 0,
         "quality": "complete", "year": 2023, "cited": 5, "in_corpus_cited": 0,
         "fields": ["zeta"]},
    ]
    corpus = {
        "definition": {"name": "Synthetic corpus", "description": "Fixture corpus."},
        "fields": {"alpha": {"name": "Alpha Field", "description": "Alpha papers."},
                   "zeta": {"name": "Zeta Field"}},
        "counts": {"works": len(works), "authors": 0, "citations": 0,
                   "coauthor_edges": 0, "institutions": 0},
        "identity": {"high": 0, "medium": 0, "low": 0},
        "quality": {"complete": 2, "partial": 0, "suspect": 0},
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
    (data / "institutions-index.json").write_text("[]")
    (data / "topics-index.json").write_text("[]")
    (data / "payloads.json").write_text("{}")
    (data / "works" / "fixture.json").write_text(json.dumps({
        work["id"]: {
            "id": work["id"], "title": work["title"], "authors": [],
            "quality": {"band": work["quality"], "sentence": "Synthetic record.", "evidence": []},
            "abstract": {"text": "", "reason": "not-in-source"},
            "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
            "topics": [], "doi": None, "oa": {"license": None, "url": None},
            "openalex_url": "", "year": work["year"], "source": {"name": ""},
            "cited_by_count": work["cited"], "in_corpus_cited_by": work["in_corpus_cited"],
            "raw": "", "type": "article", "date": None,
        }
        for work in works
    }))
    (data / "authors" / "fixture.json").write_text("{}")
    return fields, works, corpus


def unescape_json_ld(encoded: str) -> str:
    return encoded.replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&")


def find_breadcrumbs(html: str):
    blocks = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
    )
    breadcrumbs = []
    for block in blocks:
        parsed = json.loads(unescape_json_ld(block))
        if parsed.get("@type") == "BreadcrumbList":
            breadcrumbs.append(parsed)
    return breadcrumbs


def check_page(site: Path, path: str, expected_trail: list) -> int:
    bad = 0
    page = site / path / "index.html"
    bad += check(page.exists(), f"missing /{path}/")
    if not page.exists():
        return bad
    html = page.read_text()
    breadcrumbs = find_breadcrumbs(html)
    bad += check(len(breadcrumbs) == 1, f"/{path}/ does not carry exactly one BreadcrumbList block")
    if len(breadcrumbs) != 1:
        return bad
    items = breadcrumbs[0].get("itemListElement", [])
    bad += check(len(items) == len(expected_trail),
                 f"/{path}/ BreadcrumbList does not have exactly {len(expected_trail)} items")
    if len(items) != len(expected_trail):
        return bad
    bad += check(
        [item["position"] for item in items] == list(range(1, len(expected_trail) + 1)),
        f"/{path}/ BreadcrumbList positions are not contiguous 1..{len(expected_trail)}",
    )
    actual = [(item["name"], item["item"]) for item in items]
    expected = [(name, render.canonical_url(p)) for name, p in expected_trail]
    bad += check(actual == expected, f"/{path}/ BreadcrumbList trail {actual} != {expected}")
    return bad


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (render.DATA, render.SITE, render.ASSETS)
    try:
        data = tmp / "data"
        fields, works, corpus = write_fixture(data)
        render.DATA = data
        render.SITE = tmp / "site"
        render.ASSETS = Path(__file__).parent / "web" / "assets"
        bad += check(render.main() == 0, "synthetic render failed")

        site = render.SITE
        expected_pages = {
            "fields": [("Home", ""), ("Fields", "fields/")],
        }
        for field in fields:
            expected_pages[f'fields/{field["key"]}'] = [
                ("Home", ""), ("Fields", "fields/"),
                (field["name"], f'fields/{field["key"]}/'),
            ]

        for path, trail in expected_pages.items():
            bad += check_page(site, path, trail)

        # The committed release has no fields-index export at all.  Its one
        # legacy field is normalized from the top-level corpus definition and
        # must still carry a three-item trail whose leaf URL matches its
        # derived key.
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
        bad += check_page(render.SITE, f"fields/{legacy_key}", [
            ("Home", ""), ("Fields", "fields/"),
            ("Legacy Fixture Field", f"fields/{legacy_key}/"),
        ])
    finally:
        render.DATA, render.SITE, render.ASSETS = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_breadcrumb_json_ld:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
