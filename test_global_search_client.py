#!/usr/bin/env python3
"""Offline synthetic-render and browser-contract coverage for global search."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import derive
import export_json
import render
import test_entity_export


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def check(condition, message):
    if condition:
        return 0
    print(f"  FAIL: {message}")
    return 1


def tags(path: Path) -> Tags:
    parsed = Tags()
    parsed.feed(path.read_text())
    return parsed


def mixed(value: str) -> str:
    """Produce a query whose case is deliberately unlike the fixture value."""
    return "".join(char.upper() if index % 2 else char.lower()
                   for index, char in enumerate(value))


def matching(records: list[dict], query: str) -> list[dict]:
    query = query.strip().lower()
    return [record for record in records if query in record["label"].lower()
            or query in record["id"].lower()]


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH,
             export_json.ROOT, render.DATA, render.SITE, render.ASSETS)
    try:
        db_path, _, _ = test_entity_export.build_corpus(tmp)
        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "synthetic export failed")

        render.DATA = tmp / "data"
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "synthetic render failed")

        index_path = render.SITE / "data" / "search-index.json"
        records = json.loads(index_path.read_text()) if index_path.exists() else []
        routes = {"work": "w", "author": "a", "institution": "i", "topic": "t"}
        kinds = {kind: [row for row in records if row["kind"] == kind] for kind in routes}
        bad += check(all(kinds.values()), "synthetic global index lacks a fixture for a search kind")

        # Exercise mixed-case title/name lookup and ID lookup for every kind,
        # then require the link target the browser would build to exist locally.
        for kind, route in routes.items():
            row = kinds[kind][0]
            for field in ("label", "id"):
                query = mixed(row[field])
                matches = matching(records, query)
                bad += check(row in matches, f"mixed-case {kind} {field} query did not match")
                for match in matches:
                    target = render.SITE / routes[match["kind"]] / match["id"] / "index.html"
                    bad += check(target.exists(), f"global {match['kind']} result has no local detail page")

        html_pages = list(render.SITE.rglob("*.html"))
        bad += check(bool(html_pages), "synthetic render produced no HTML")
        for page in html_pages:
            parsed = tags(page)
            globals_ = [attrs for tag, attrs in parsed.tags
                        if tag == "form" and "data-global-search" in attrs]
            bad += check(len(globals_) == 1, f"{page.relative_to(render.SITE)} lacks one header search")
            if globals_:
                expected_index = "./data/search-index.json" if page.parent == render.SITE else (
                    "../" * len(page.parent.relative_to(render.SITE).parts) + "data/search-index.json")
                bad += check(globals_[0].get("data-index") == expected_index,
                             f"{page.relative_to(render.SITE)} has the wrong global index depth")
            scripts = [attrs for tag, attrs in parsed.tags
                       if tag == "script" and attrs.get("src", "").endswith("assets/app.js")]
            bad += check(len(scripts) == 1 and "defer" in scripts[0],
                         f"{page.relative_to(render.SITE)} does not defer exactly one app.js")

        browse = tags(render.SITE / "works" / "index.html")
        ids = [attrs["id"] for _, attrs in browse.tags if "id" in attrs]
        bad += check(len(ids) == len(set(ids)), "browse page has duplicate search IDs")
        bad += check(any("data-collection-search" in attrs for _, attrs in browse.tags),
                     "browse page lacks its collection-specific search control")

        client = (Path(__file__).parent / "web" / "assets" / "app.js").read_text()
        required = (
            "var MAX_RESULTS = 60;",
            "if (!query) return;",
            "loadGlobal(form.dataset.index)",
            "if (globalRows) return Promise.resolve(globalRows);",
            "normalized(row.label).indexOf(query)",
            "normalized(row.id).indexOf(query)",
            "matches.slice(0, MAX_RESULTS)",
            "document.createTextNode(label)",
            "meta.textContent = detail;",
            "No results match your search.",
            "Search is unavailable. Please try again.",
            "data-collection-search",
            "table.hidden = false;",
            "table.hidden = true;",
        )
        for contract in required:
            bad += check(contract in client, f"client contract missing: {contract}")
        bad += check("innerHTML" not in client,
                     "search result labels are not exclusively inserted as DOM text")
        empty_guard = client.find("if (!query) return;")
        global_load = client.find("loadGlobal(form.dataset.index)")
        bad += check(0 <= empty_guard < global_load,
                     "global index can be fetched before a non-empty query")
        bad += check("data-index=\"../data/works-index.json\"" in
                     (render.SITE / "works" / "index.html").read_text(),
                     "browse search no longer names its copied local index")

        readme = (Path(__file__).parent / "README.md").read_text()
        bad += check("does not\nrequest its local index until the reader enters a non-empty query" in readme
                     and "no search service,\nserver endpoint, or Node runtime" in readme,
                     "README does not document the deferred local no-service boundary")
    finally:
        (derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH,
         export_json.ROOT, render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_global_search_client:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
