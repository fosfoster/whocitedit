#!/usr/bin/env python3
"""Author pages declare the exported fields of their held works."""
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


ROOT = Path(__file__).parent
BANDS = {"high": "High confidence"}


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def author(aid, works):
    return {
        "id": aid, "name": f"Author {aid}", "orcid": None,
        "openalex_url": f"https://openalex.org/{aid}",
        "confidence": {"band": "high", "evidence": []},
        "in_corpus": {"works": len(works), "hindex": 1},
        "cited_by_count": 10, "works_count": len(works),
        "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
        "works": [{"id": wid, "title": f"Work {wid}", "position": "first",
                   "year": 2024, "cited": 10} for wid in works],
        "institutions": [],
    }


def membership_links(page):
    sections = re.findall(
        r'<section class="author-field-memberships" '
        r'aria-labelledby="author-field-memberships-heading">(.*?)</section>',
        page,
        re.S,
    )
    if not sections:
        return sections, []
    return sections, [
        (html.unescape(href), html.unescape(label))
        for href, label in re.findall(r'<a href="([^"]+)">(.*?)</a>', sections[0], re.S)
    ]


def direct_render_coverage():
    """Memberships are a NAV_FIELDS-ordered union of exported work fields."""
    bad = 0
    hostile_key = 'hostile"><img src=x onerror="bad">'
    hostile_name = 'Hostile <img src=x onerror="bad"> field'
    saved = render.NAV_FIELDS
    try:
        # This order is deliberately neither alphabetical nor work order.
        render.NAV_FIELDS = [
            {"key": "zeta", "name": "Zeta Field"},
            {"key": "alpha", "name": "Alpha Field"},
            {"key": hostile_key, "name": hostile_name},
        ]
        work_fields = {
            "W-alpha": ["alpha", "alpha"],
            "W-zeta": ["zeta", "zeta"],
            "W-hostile": [hostile_key],
        }
        cross = render.render_author(
            author("A-cross", ["W-alpha", "W-zeta", "W-absent"]), {}, BANDS, {}, set(),
            None, work_fields,
        )
        sections, links = membership_links(cross)
        bad += check(len(sections) == 1,
                     "cross-field direct author did not render exactly one Fields section")
        bad += check(links == [
            ("../../fields/zeta/", "Zeta Field"),
            ("../../fields/alpha/", "Alpha Field"),
        ], "cross-field direct author is not NAV_FIELDS-ordered, deduplicated membership")

        single = render.render_author(
            author("A-single", ["W-alpha"]), {}, BANDS, {}, set(), None, work_fields,
        )
        _, links = membership_links(single)
        bad += check(links == [("../../fields/alpha/", "Alpha Field")],
                     "single-field direct author rendered another field")

        repeated = render.render_author(
            author("A-repeated", ["W-alpha", "W-alpha"]), {}, BANDS, {}, set(), None, work_fields,
        )
        _, links = membership_links(repeated)
        bad += check(links == [("../../fields/alpha/", "Alpha Field")],
                     "repeated work fields were not emitted once")

        missing = render.render_author(
            author("A-missing", ["W-absent"]), {}, BANDS, {}, set(), None, work_fields,
        )
        sections, _ = membership_links(missing)
        bad += check(not sections,
                     "an absent work-field map entry invented an author Fields section")

        hostile = render.render_author(
            author("A-hostile", ["W-hostile"]), {}, BANDS, {}, set(), None, work_fields,
        )
        _, links = membership_links(hostile)
        bad += check(links == [(f"../../fields/{hostile_key}/", hostile_name)],
                     "hostile exported field key or name did not round-trip through escaping")
        bad += check(html.escape(hostile_key, quote=True) in hostile
                     and html.escape(hostile_name, quote=True) in hostile
                     and '<img src=x onerror="bad">' not in hostile,
                     "hostile field metadata injected markup into the author page")
    finally:
        render.NAV_FIELDS = saved
    return bad


def work_index(wid, title, fields=None):
    value = {"id": wid, "title": title, "authors": [], "n_authors": 0,
             "quality": "complete", "year": 2024, "cited": 10, "in_corpus_cited": 0}
    if fields is not None:
        value["fields"] = fields
    return value


def work_detail(row):
    value = {
        "id": row["id"], "title": row["title"], "authors": [],
        "quality": {"band": "complete", "sentence": "Synthetic record.", "evidence": []},
        "abstract": {"text": "", "reason": "not-in-source"},
        "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
        "topics": [], "doi": None, "oa": {"license": None, "url": None},
        "openalex_url": "", "year": row["year"], "source": {"name": ""},
        "cited_by_count": row["cited"], "in_corpus_cited_by": row["in_corpus_cited"],
        "raw": "", "type": "article", "date": None,
    }
    if "fields" in row:
        value["fields"] = list(row["fields"])
    return value


def author_index(value):
    return {"id": value["id"], "name": value["name"], "band": "high",
            "works": len(value["works"]), "coauthors": 0, "cited": 10}


def write_fixture(data, definition, works, authors, fields=None):
    corpus = {
        "definition": definition,
        "counts": {"works": len(works), "authors": len(authors), "citations": 0,
                   "coauthor_edges": 0, "institutions": 0},
        "identity": {"high": len(authors), "medium": 0, "low": 0},
        "quality": {"complete": len(works), "partial": 0, "suspect": 0},
        "abstracts": {}, "sources": [], "identity_notes": {},
        "identity_bands": {"high": "High confidence", "medium": "", "low": ""},
        "quality_notes": {},
    }
    (data / "works").mkdir(parents=True)
    (data / "authors").mkdir()
    (data / "corpus.json").write_text(json.dumps(corpus))
    (data / "works-index.json").write_text(json.dumps(works))
    (data / "authors-index.json").write_text(json.dumps([author_index(a) for a in authors]))
    (data / "payloads.json").write_text("{}")
    if fields is not None:
        (data / "fields-index.json").write_text(json.dumps(fields))
    (data / "works" / "fixture.json").write_text(json.dumps({
        row["id"]: work_detail(row) for row in works
    }))
    (data / "authors" / "fixture.json").write_text(json.dumps({
        value["id"]: value for value in authors
    }))


def main_render_coverage():
    """The main build passes exported and legacy work memberships to authors."""
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS
    try:
        render.ASSETS = ROOT / "web" / "assets"
        fields = [
            {"key": "zeta", "name": "Zeta Field", "description": None, "works": 2},
            {"key": "alpha", "name": "Alpha Field", "description": None, "works": 2},
        ]
        works = [
            work_index("W-alpha", "Alpha paper", ["alpha"]),
            work_index("W-both", "Both fields paper", ["alpha", "zeta"]),
            work_index("W-zeta", "Zeta paper", ["zeta"]),
        ]
        authors = [
            author("A-cross", ["W-alpha", "W-both"]),
            author("A-single", ["W-alpha"]),
        ]
        data = tmp / "multi-data"
        write_fixture(data, {"name": "Synthetic multi-field corpus", "description": "Fixture."},
                      works, authors, fields)
        render.DATA, render.SITE = data, tmp / "multi-site"
        bad += check(render.main() == 0, "multi-field synthetic render failed")
        expected = {
            "A-cross": [("../../fields/zeta/", "Zeta Field"),
                        ("../../fields/alpha/", "Alpha Field")],
            "A-single": [("../../fields/alpha/", "Alpha Field")],
        }
        for aid, memberships in expected.items():
            page = (render.SITE / "a" / aid / "index.html").read_text()
            sections, links = membership_links(page)
            bad += check(len(sections) == 1 and links == memberships,
                         f"a/{aid}/ did not render its exact exported memberships: {links}")
            for href, _ in links:
                key = href.split("/")[-2]
                bad += check((render.SITE / "fields" / key / "index.html").exists(),
                             f"a/{aid}/ links fields/{key}/ that this build did not emit")

        legacy_definition = {"name": "Legacy Fixture Field", "description": "One old field."}
        legacy_key = corpus_contract.field_key(legacy_definition["name"])
        legacy_data = tmp / "legacy-data"
        write_fixture(legacy_data, legacy_definition,
                      [work_index("W-legacy", "Legacy paper")],
                      [author("A-legacy", ["W-legacy"])])
        render.DATA, render.SITE = legacy_data, tmp / "legacy-site"
        bad += check(render.main() == 0, "legacy synthetic render failed")
        legacy_page = (render.SITE / "a" / "A-legacy" / "index.html").read_text()
        sections, links = membership_links(legacy_page)
        bad += check(len(sections) == 1
                     and links == [(f"../../fields/{legacy_key}/", legacy_definition["name"])],
                     "legacy author did not inherit its normalized sole field")
        bad += check((render.SITE / "fields" / legacy_key / "index.html").exists(),
                     "legacy author links a field page the same build did not emit")
    finally:
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(tmp, ignore_errors=True)
    return bad


def main() -> int:
    bad = direct_render_coverage() + main_render_coverage()
    print("test_author_field_membership:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
