#!/usr/bin/env python3
"""Offline coverage for the BreadcrumbList JSON-LD on the four browse pages."""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def write_fixture(data: Path):
    works = [
        {"id": "W1", "title": "Only paper", "authors": [], "n_authors": 0,
         "quality": "complete", "year": 2024, "cited": 10, "in_corpus_cited": 0,
         "fields": ["alpha"]},
    ]
    corpus = {
        "definition": {"name": "Synthetic corpus", "description": "Fixture corpus."},
        "fields": {"alpha": {"name": "Alpha Field", "description": "Alpha papers."}},
        "counts": {"works": len(works), "authors": 0, "citations": 0,
                   "coauthor_edges": 0, "institutions": 0},
        "identity": {"high": 0, "medium": 0, "low": 0},
        "quality": {"complete": 1, "partial": 0, "suspect": 0},
        "abstracts": {}, "sources": [], "identity_notes": {},
        "identity_bands": {"high": "", "medium": "", "low": ""},
        "quality_notes": {},
    }
    (data / "works").mkdir(parents=True)
    (data / "authors").mkdir()
    (data / "corpus.json").write_text(json.dumps(corpus))
    (data / "works-index.json").write_text(json.dumps(works))
    (data / "fields-index.json").write_text(json.dumps([
        {"key": "alpha", "name": "Alpha Field", "description": "Alpha papers.", "works": 1},
    ]))
    (data / "authors-index.json").write_text("[]")
    (data / "institutions-index.json").write_text("[]")
    (data / "topics-index.json").write_text("[]")
    (data / "payloads.json").write_text("{}")
    (data / "works" / "fixture.json").write_text(json.dumps({
        "W1": {
            "id": "W1", "title": "Only paper", "authors": [],
            "quality": {"band": "complete", "sentence": "Synthetic record.", "evidence": []},
            "abstract": {"text": "", "reason": "not-in-source"},
            "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
            "topics": [], "doi": None, "oa": {"license": None, "url": None},
            "openalex_url": "", "year": 2024, "source": {"name": ""},
            "cited_by_count": 10, "in_corpus_cited_by": 0,
            "raw": "", "type": "article", "date": None,
        }
    }))
    (data / "authors" / "fixture.json").write_text("{}")


def unescape_json_ld(encoded: str) -> str:
    return encoded.replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&")


def find_breadcrumb(html: str):
    blocks = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
    )
    for block in blocks:
        parsed = json.loads(unescape_json_ld(block))
        if parsed.get("@type") == "BreadcrumbList":
            return parsed
    return None


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (render.DATA, render.SITE, render.ASSETS)
    try:
        data = tmp / "data"
        write_fixture(data)
        render.DATA = data
        render.SITE = tmp / "site"
        render.ASSETS = Path(__file__).parent / "web" / "assets"
        bad += check(render.main() == 0, "synthetic render failed")

        site = render.SITE
        root_url = render.canonical_url("")
        pages = {
            "works": "Papers",
            "authors": "Authors",
            "institutions": "Institutions",
            "topics": "Topics",
        }
        for kind, title in pages.items():
            page = site / kind / "index.html"
            bad += check(page.exists(), f"missing /{kind}/")
            if not page.exists():
                continue
            html = page.read_text()
            breadcrumb = find_breadcrumb(html)
            bad += check(breadcrumb is not None, f"/{kind}/ has no BreadcrumbList block")
            if breadcrumb is None:
                continue
            items = breadcrumb.get("itemListElement", [])
            bad += check(len(items) == 2, f"/{kind}/ BreadcrumbList does not have exactly 2 items")
            if len(items) != 2:
                continue
            bad += check(
                [item["position"] for item in items] == [1, 2],
                f"/{kind}/ BreadcrumbList positions are not contiguous 1..2",
            )
            bad += check(
                items[0]["item"] == root_url,
                f"/{kind}/ BreadcrumbList first item does not name the site root URL",
            )
            bad += check(
                items[1]["item"] == render.canonical_url(f"{kind}/"),
                f"/{kind}/ BreadcrumbList second item does not name this listing's canonical URL",
            )
    finally:
        render.DATA, render.SITE, render.ASSETS = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_breadcrumb_json_ld:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
