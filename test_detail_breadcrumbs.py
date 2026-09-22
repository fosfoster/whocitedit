#!/usr/bin/env python3
"""Offline BreadcrumbList JSON-LD coverage for entity detail pages."""
import json
import re
import sys

import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def metadata(page):
    head = page.split("</head>", 1)[0]
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', head, re.S)
    return [json.loads(block) for block in blocks]


def detail_pages():
    work = {
        "id": "W123", "title": "Breadcrumb Work", "year": 2024, "date": None,
        "doi": None, "source": {"id": None, "name": None},
        "oa": {"url": None, "license": None},
        "abstract": {"text": None, "reason": "not-in-source"},
        "cited_by_count": 0, "in_corpus_cited_by": 0, "authors": [], "topics": [],
        "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
        "quality": {"band": "complete", "sentence": "Complete", "evidence": []},
        "raw": None, "openalex_url": "https://openalex.org/W123",
    }
    author = {
        "id": "A123", "name": "Breadcrumb Author", "orcid": None,
        "openalex_url": "https://openalex.org/A123",
        "confidence": {"band": "high", "evidence": []},
        "in_corpus": {"works": 0, "hindex": 0}, "cited_by_count": 0,
        "works_count": 0, "works": [], "institutions": [],
        "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
    }
    institution = {
        "id": "I123", "name": "Breadcrumb Institution",
        "metadata": {"ror": None, "country_code": "US", "type": "education"},
        "authors": [], "works": [],
        "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
        "raw": None, "openalex_url": "https://openalex.org/I123",
    }
    topic = {
        "id": "T123", "name": "Breadcrumb Topic",
        "metadata": {"field": "Fixture Field", "domain": "Fixture Domain"},
        "authors": [], "works": [], "raw": None,
        "openalex_url": "https://openalex.org/T123",
    }
    return [
        ("work", render.render_work(work, {}, {}, {}, {}, set()), "ScholarlyArticle",
         [("Home", ""), ("Papers", "works/"), (work["title"], "w/W123/")]),
        ("author", render.render_author(author, {}, {"high": "High confidence"}, {}, set()), "Person",
         [("Home", ""), ("Authors", "authors/"), (author["name"], "a/A123/")]),
        ("institution", render.render_institution(institution, {}, set(), set()), "Organization",
         [("Home", ""), ("Institutions", "institutions/"), (institution["name"], "i/I123/")]),
        ("topic", render.render_topic(topic, {}, set(), set()), "DefinedTerm",
         [("Home", ""), ("Topics", "topics/"), (topic["name"], "t/T123/")]),
    ]


def check_page(label, page, entity_type, trail):
    bad = 0
    blocks = metadata(page)
    bad += check(len(blocks) == 2, f"{label} head does not contain exactly two JSON-LD blocks")
    bad += check(bool(blocks) and blocks[0].get("@type") == entity_type,
                 f"{label} entity JSON-LD is not the first block")
    bad += check(any(block.get("@type") == entity_type for block in blocks),
                 f"{label} entity JSON-LD is missing")

    breadcrumbs = [block for block in blocks if block.get("@type") == "BreadcrumbList"]
    bad += check(len(breadcrumbs) == 1, f"{label} BreadcrumbList JSON-LD is missing")
    if len(breadcrumbs) != 1:
        return bad
    breadcrumb = breadcrumbs[0]
    items = breadcrumb.get("itemListElement", [])
    bad += check(breadcrumb.get("@context") == "https://schema.org",
                 f"{label} BreadcrumbList has the wrong @context")
    bad += check(isinstance(items, list) and len(items) == 3,
                 f"{label} BreadcrumbList does not have exactly three ListItems")
    if not isinstance(items, list) or len(items) != 3:
        return bad
    bad += check(all(item.get("@type") == "ListItem" for item in items),
                 f"{label} BreadcrumbList contains a non-ListItem")
    bad += check([item.get("position") for item in items] == [1, 2, 3],
                 f"{label} BreadcrumbList positions are not contiguous 1..3")
    actual = [(item.get("name"), item.get("item")) for item in items]
    expected = [(name, render.canonical_url(path)) for name, path in trail]
    bad += check(actual == expected, f"{label} BreadcrumbList trail {actual} != {expected}")
    return bad


def main() -> int:
    bad = 0
    for page in detail_pages():
        bad += check_page(*page)
    print("test_detail_breadcrumbs:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
