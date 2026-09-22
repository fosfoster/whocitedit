#!/usr/bin/env python3
"""Audit BreadcrumbList JSON-LD on the works and authors browse listings."""
import json
from pathlib import Path
import re
import sys

import render


ROOT = Path(__file__).parent
DATA = ROOT / "web" / "data"
JSON_LD_BLOCKS = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL
)
BROWSE_LISTINGS = {
    "works": "Papers",
    "authors": "Authors",
}


def breadcrumb_lists(metadata: object) -> list[dict]:
    """Find BreadcrumbList nodes whether standalone or nested in JSON-LD."""
    if isinstance(metadata, dict):
        found = [metadata] if metadata.get("@type") == "BreadcrumbList" else []
        return found + [
            breadcrumb
            for value in metadata.values()
            for breadcrumb in breadcrumb_lists(value)
        ]
    if isinstance(metadata, list):
        return [
            breadcrumb
            for value in metadata
            for breadcrumb in breadcrumb_lists(value)
        ]
    return []


def breadcrumbs_in_head(html: str) -> tuple[list[dict], str | None]:
    if "</head>" not in html:
        return [], "page head is missing"
    breadcrumbs = []
    for block in JSON_LD_BLOCKS.findall(html.split("</head>", 1)[0]):
        try:
            metadata = json.loads(block)
        except json.JSONDecodeError as error:
            return [], f"page head contains malformed JSON-LD: {error.msg}"
        breadcrumbs.extend(breadcrumb_lists(metadata))
    return breadcrumbs, None


def audit_listing(kind: str, title: str, html: str) -> str | None:
    label = f"/{kind}/"
    breadcrumbs, error = breadcrumbs_in_head(html)
    if error:
        return f"{label} {error}"
    if len(breadcrumbs) != 1:
        return (
            f"{label} expected exactly one BreadcrumbList in the page head, "
            f"found {len(breadcrumbs)}"
        )

    breadcrumb = breadcrumbs[0]
    items = breadcrumb.get("itemListElement")
    if breadcrumb.get("@context") != "https://schema.org":
        return f"{label} BreadcrumbList has the wrong @context"
    if not isinstance(items, list) or len(items) != 2:
        return f"{label} BreadcrumbList must contain exactly two ListItems"
    if not all(
        isinstance(item, dict) and item.get("@type") == "ListItem"
        for item in items
    ):
        return f"{label} BreadcrumbList contains a malformed ListItem"

    expected = [
        (1, "Home", render.canonical_url("")),
        (2, title, render.canonical_url(f"{kind}/")),
    ]
    actual = [
        (item.get("position"), item.get("name"), item.get("item"))
        for item in items
    ]
    if actual != expected:
        return f"{label} BreadcrumbList trail {actual!r} != {expected!r}"
    return None


def main() -> int:
    corpus = json.loads((DATA / "corpus.json").read_text())
    failures = []
    for kind, title in BROWSE_LISTINGS.items():
        rows = json.loads((DATA / f"{kind}-index.json").read_text())
        failure = audit_listing(kind, title, render.render_browse(kind, rows, corpus))
        if failure:
            failures.append(failure)

    if failures:
        print("test_browse_listing_breadcrumbs_pair_one: FAILED:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print("test_browse_listing_breadcrumbs_pair_one: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
