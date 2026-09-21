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


def load_index_ids(name: str, kind: str) -> set[str]:
    data = json.loads((DATA / name).read_text())
    if not isinstance(data, list):
        raise AssertionError(f"{name} is not a list")
    identifiers = []
    for row in data:
        identifier = row.get("id") if isinstance(row, dict) else None
        if not isinstance(identifier, str) or not identifier:
            raise AssertionError(f"{kind} index row has no usable ID: {row!r}")
        identifiers.append(identifier)
    if len(identifiers) != len(set(identifiers)):
        duplicate = next(i for i in identifiers if identifiers.count(i) > 1)
        raise AssertionError(f"{kind} {duplicate!r}: duplicate ID in {name}")
    return set(identifiers)


def load_committed_records(directory: str, kind: str) -> dict[str, dict]:
    records = {}
    for shard in sorted((DATA / directory).glob("*.json")):
        data = json.loads(shard.read_text())
        if not isinstance(data, dict):
            raise AssertionError(f"{shard.relative_to(ROOT)} is not an object")
        for identifier, row in data.items():
            label = f"{kind} {identifier!r}"
            if not isinstance(identifier, str) or not identifier:
                raise AssertionError(f"{label}: shard key is not a usable ID")
            if identifier in records:
                raise AssertionError(f"{label}: duplicate ID in committed shards")
            if not isinstance(row, dict) or row.get("id") != identifier:
                raise AssertionError(f"{label}: shard record has a mismatched ID")
            records[identifier] = row
    return records


def canonical_url(path: str) -> str:
    return f"{SITE_URL}/{path}".rstrip("/") or SITE_URL


def breadcrumb_lists(metadata: object) -> list[dict]:
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
    """Return BreadcrumbList blocks, or explain a malformed head JSON-LD block."""
    if "</head>" not in html:
        return [], "page head is missing"
    breadcrumbs = []
    for block in JSON_LD_BLOCKS.findall(html.split("</head>", 1)[0]):
        try:
            metadata = json.loads(block)
        except json.JSONDecodeError:
            return [], "page head contains malformed JSON-LD"
        breadcrumbs.extend(breadcrumb_lists(metadata))
    return breadcrumbs, None


def rendered_pages(site: Path, prefix: str) -> dict[str, Path]:
    return {
        page.parent.name: page
        for page in sorted((site / prefix).glob("*/index.html"))
    }


def audit_page(page: Path, kind: str, identifier: str, row: dict | None) -> str | None:
    name_key = "title" if kind == "work" else "name"
    collection, collection_path, prefix = (
        ("Papers", "works", "w") if kind == "work" else ("Authors", "authors", "a")
    )
    label = f"{kind} {identifier!r}"
    if row is None:
        return f"{label}: rendered page has no committed shard record"
    if not isinstance(row.get(name_key), str):
        return f"{label}: shard record has no usable {name_key}"

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
        indexes = {
            "work": load_index_ids("works-index.json", "work"),
            "author": load_index_ids("authors-index.json", "author"),
        }
        records = {
            "work": load_committed_records("works", "work"),
            "author": load_committed_records("authors", "author"),
        }
        with rendered_site() as site:
            pages = {
                "work": rendered_pages(site, "w"),
                "author": rendered_pages(site, "a"),
            }
            failures = []
            for kind in ("work", "author"):
                for identifier in sorted(indexes[kind] - records[kind].keys()):
                    failures.append(
                        f"{kind} {identifier!r}: indexed ID has no committed shard record"
                    )
                for identifier in sorted(records[kind].keys() - pages[kind].keys()):
                    failures.append(
                        f"{kind} {identifier!r}: committed shard page was not rendered"
                    )
                for identifier, page in pages[kind].items():
                    failure = audit_page(
                        page, kind, identifier, records[kind].get(identifier)
                    )
                    if failure:
                        failures.append(failure)
    except AssertionError as error:
        print(f"test_full_corpus_breadcrumbs: FAILED: {error}")
        return 1

    print(
        "test_full_corpus_breadcrumbs: audited "
        f"works={len(pages['work'])} authors={len(pages['author'])}"
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
