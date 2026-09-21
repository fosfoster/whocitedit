#!/usr/bin/env python3
"""Audit BreadcrumbList JSON-LD for every committed work and author page."""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

import render


ROOT = Path(__file__).parent
DATA = ROOT / "web" / "data"
ASSETS = ROOT / "web" / "assets"
SITE_URL = "https://whocitedit.com"
JSON_LD_BLOCKS = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL
)


@contextmanager
def rendered_site():
    """Render committed inputs into a disposable site."""
    saved = render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS
    temporary = Path(tempfile.mkdtemp())
    try:
        render.DATA = DATA
        render.SITE = temporary / "site"
        render.ASSETS = ASSETS
        if render.main() != 0:
            raise AssertionError("render.main() failed for the committed corpus")
        yield render.SITE
    finally:
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(temporary, ignore_errors=True)


def load_index(name: str) -> list[dict]:
    data = json.loads((DATA / name).read_text())
    if not isinstance(data, list):
        raise AssertionError(f"{name} is not a list")
    return data


def canonical_url(path: str) -> str:
    return f"{SITE_URL}/{path}".rstrip("/") or SITE_URL


def breadcrumbs_in_head(html: str) -> tuple[list[dict], str | None]:
    """Return BreadcrumbList blocks, or explain a malformed head JSON-LD block."""
    if "</head>" not in html:
        return [], "page head is missing"
    breadcrumbs = []
    for block in JSON_LD_BLOCKS.findall(html.split("</head>", 1)[0]):
        try:
            metadata = json.loads(block)
        except json.JSONDecodeError:
            return [], "page head contains malformed JSON-LD"
        if isinstance(metadata, dict) and metadata.get("@type") == "BreadcrumbList":
            breadcrumbs.append(metadata)
    return breadcrumbs, None


def audit_page(site: Path, kind: str, row: dict) -> str | None:
    identifier = row.get("id")
    name_key = "title" if kind == "work" else "name"
    collection, collection_path, prefix = (
        ("Papers", "works", "w") if kind == "work" else ("Authors", "authors", "a")
    )
    label = f"{kind} {identifier!r}"
    if not isinstance(identifier, str) or not identifier:
        return f"{label}: index row has no usable ID"
    if not isinstance(row.get(name_key), str):
        return f"{label}: index row has no usable {name_key}"

    page = site / prefix / identifier / "index.html"
    if not page.exists():
        return f"{label}: rendered page is missing"
    breadcrumbs, error = breadcrumbs_in_head(page.read_text())
    if error:
        return f"{label}: {error}"
    if len(breadcrumbs) != 1:
        return f"{label}: expected exactly one BreadcrumbList in the page head, found {len(breadcrumbs)}"

    breadcrumb = breadcrumbs[0]
    items = breadcrumb.get("itemListElement")
    if breadcrumb.get("@context") != "https://schema.org":
        return f"{label}: BreadcrumbList has the wrong @context"
    if not isinstance(items, list) or len(items) != 3:
        return f"{label}: BreadcrumbList must contain exactly three ListItems"
    if not all(isinstance(item, dict) and item.get("@type") == "ListItem" for item in items):
        return f"{label}: BreadcrumbList contains a malformed ListItem"

    expected = [
        (1, "Home", canonical_url("")),
        (2, collection, canonical_url(f"{collection_path}/")),
        (3, row[name_key], canonical_url(f"{prefix}/{identifier}/")),
    ]
    actual = [
        (item.get("position"), item.get("name"), item.get("item"))
        for item in items
    ]
    if actual != expected:
        return f"{label}: BreadcrumbList trail {actual!r} != {expected!r}"
    return None


def main() -> int:
    try:
        works = load_index("works-index.json")
        authors = load_index("authors-index.json")
        with rendered_site() as site:
            failures = [
                failure
                for kind, rows in (("work", works), ("author", authors))
                for row in rows
                if (failure := audit_page(site, kind, row))
            ]
    except AssertionError as error:
        print(f"test_full_corpus_breadcrumbs: FAILED: {error}")
        return 1

    print(
        "test_full_corpus_breadcrumbs: audited "
        f"works={len(works)} authors={len(authors)}"
    )
    if failures:
        print("test_full_corpus_breadcrumbs: FAILED:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print("test_full_corpus_breadcrumbs: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
