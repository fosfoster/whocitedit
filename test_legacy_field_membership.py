#!/usr/bin/env python3
"""Every work page of a legacy corpus declares the one normalized field.

The checked-in release predates the membership export: its ``corpus.json`` has
only a top-level ``definition``, there is no ``fields-index.json``, and neither
the works-index rows nor the work shard payloads carry ``fields``.  ``render``
still owes each of those work pages its Fields section, so this drives
``render.main()`` over that exact shape rather than handing ``render_work`` a
dict that already has the key.
"""
from __future__ import annotations

import html
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
    """One work shard payload.  ``fields`` appears only when exported."""
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


def write_fixture(data: Path, definition: dict, works: list,
                  definitions: dict | None = None, fields: list | None = None):
    """Write a DATA directory.  Without ``definitions``/``fields`` it is legacy."""
    corpus = {
        "definition": definition,
        "counts": {"works": len(works), "authors": 0, "citations": 0,
                   "coauthor_edges": 0, "institutions": 0},
        "identity": {"high": 0, "medium": 0, "low": 0},
        "quality": {"complete": len(works), "partial": 0, "suspect": 0},
        "abstracts": {}, "sources": [], "identity_notes": {},
        "identity_bands": {"high": "", "medium": "", "low": ""},
        "quality_notes": {},
    }
    if definitions is not None:
        corpus["fields"] = definitions
    (data / "works").mkdir(parents=True)
    (data / "authors").mkdir()
    (data / "corpus.json").write_text(json.dumps(corpus))
    (data / "works-index.json").write_text(json.dumps(works))
    (data / "authors-index.json").write_text("[]")
    (data / "payloads.json").write_text("{}")
    if fields is not None:
        (data / "fields-index.json").write_text(json.dumps(fields))
    (data / "works" / "fixture.json").write_text(json.dumps({
        work["id"]: detail(work) for work in works
    }))
    (data / "authors" / "fixture.json").write_text("{}")


def index_row(wid, title, year, fields=None):
    row = {"id": wid, "title": title, "authors": [], "n_authors": 0,
           "quality": "complete", "year": year, "cited": 10, "in_corpus_cited": 0}
    if fields is not None:
        row["fields"] = fields
    return row


def membership_links(page):
    """The labelled Fields sections on one work page, and the first one's links."""
    sections = re.findall(
        r'<section class="field-memberships" aria-labelledby="field-memberships-heading">(.*?)</section>',
        page,
        re.S,
    )
    if not sections:
        return sections, []
    return sections, [
        (html.unescape(href), html.unescape(label))
        for href, label in re.findall(r'<a href="([^"]+)">(.*?)</a>', sections[0], re.S)
    ]


def rendered_work_pages(site: Path):
    return {path.name: (path / "index.html").read_text()
            for path in sorted((site / "w").iterdir())
            if (path / "index.html").exists()}


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (render.DATA, render.SITE, render.ASSETS, getattr(render, "NAV_FIELDS", []))
    try:
        render.ASSETS = Path(__file__).parent / "web" / "assets"

        # The committed release's shape: one top-level definition, no
        # fields-index.json, no `fields` on the index rows or the shards.
        definition = {
            "name": "Artificial Intelligence & Robotics",
            "description": "One legacy field.",
            "max_works": 3,
        }
        legacy_key = corpus_contract.field_key(definition["name"])
        bad += check(legacy_key == "artificial-intelligence-robotics",
                     f"legacy field name normalized to an unexpected key: {legacy_key}")
        legacy_works = [
            index_row("W-legacy-first", "Legacy first", 2024),
            index_row("W-legacy-second", "Legacy second", 2023),
            index_row("W-legacy-third", "Legacy third", 2022),
        ]
        legacy_data = tmp / "legacy-data"
        write_fixture(legacy_data, definition, legacy_works)
        bad += check(
            all("fields" not in row for row in json.loads(
                (legacy_data / "works-index.json").read_text()))
            and all("fields" not in payload for payload in json.loads(
                (legacy_data / "works" / "fixture.json").read_text()).values())
            and not (legacy_data / "fields-index.json").exists()
            and "fields" not in json.loads((legacy_data / "corpus.json").read_text()),
            "legacy fixture was not written without any field export surface",
        )

        render.DATA = legacy_data
        render.SITE = tmp / "legacy-site"
        bad += check(render.main() == 0, "legacy render failed")

        pages = rendered_work_pages(render.SITE)
        bad += check(sorted(pages) == sorted(work["id"] for work in legacy_works),
                     f"legacy render did not write one page per indexed work: {sorted(pages)}")
        for wid, page in pages.items():
            sections, links = membership_links(page)
            bad += check(len(sections) == 1,
                         f"/w/{wid}/ has {len(sections)} field-memberships sections, not one")
            bad += check(links == [(f"../../fields/{legacy_key}/", definition["name"])],
                         f"/w/{wid}/ does not link the one legacy field once: {links}")
        bad += check((render.SITE / "fields" / legacy_key / "index.html").exists(),
                     f"legacy work pages link /fields/{legacy_key}/, which was not rendered")

        # A real multi-field export owns its memberships.  The legacy default
        # must not reach these works: each keeps exactly its exported keys.
        multi_definition = {"name": "Synthetic multi-field corpus",
                            "description": "Fixture corpus."}
        definitions = {
            "alpha": {"name": "Alpha Field", "description": "Alpha papers."},
            "zeta": {"name": "Zeta Field"},
        }
        fields = [
            {"key": "alpha", "name": "Alpha Field", "description": "Alpha papers.", "works": 2},
            {"key": "zeta", "name": "Zeta Field", "description": None, "works": 2},
        ]
        multi_works = [
            index_row("W-alpha-only", "Alpha only", 2024, ["alpha"]),
            index_row("W-shared", "Shared paper", 2023, ["alpha", "zeta"]),
            index_row("W-zeta-only", "Zeta only", 2022, ["zeta"]),
        ]
        multi_data = tmp / "multi-data"
        write_fixture(multi_data, multi_definition, multi_works, definitions, fields)
        render.DATA = multi_data
        render.SITE = tmp / "multi-site"
        bad += check(render.main() == 0, "multi-field render failed")

        names = {field["key"]: field["name"] for field in fields}
        expected = {work["id"]: [(f'../../fields/{key}/', names[key])
                                 for key in work["fields"]]
                    for work in multi_works}
        pages = rendered_work_pages(render.SITE)
        bad += check(sorted(pages) == sorted(expected),
                     f"multi-field render did not write one page per indexed work: {sorted(pages)}")
        multi_legacy_key = corpus_contract.field_key(multi_definition["name"])
        for wid, page in pages.items():
            sections, links = membership_links(page)
            bad += check(len(sections) == 1,
                         f"/w/{wid}/ has {len(sections)} field-memberships sections, not one")
            bad += check(links == expected.get(wid),
                         f"/w/{wid}/ does not render exactly its exported fields: {links}")
            bad += check(f"/fields/{multi_legacy_key}/" not in page,
                         f"/w/{wid}/ was given a legacy default field alongside its export")
    finally:
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_legacy_field_membership:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
