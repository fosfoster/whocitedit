#!/usr/bin/env python3
"""Render the methodology source-field comparison matrix from synthetic works."""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import quality
import render


FIELDS = ("title", "venue", "date")


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def assertion(source, value, raw):
    return {"source": source, "value": value, "raw": raw}


def field_verdicts(**overrides):
    return {field: overrides.get(field, quality.UNAVAILABLE) for field in FIELDS}


def comparison(work_id, verdicts, sources):
    result = {"role": "Synthetic parallel observations; neither source corrects another."}
    for field in FIELDS:
        result[field] = {
            "openalex": assertion("OpenAlex", f"OpenAlex {field} {work_id}", f"oa-{field}-{work_id}"),
            "crossref": [],
            "europepmc": [],
            "status": verdicts[field],
        }
        for source in sources.get(field, ()):
            result[field][source].append(assertion(
                render.SOURCE_LABELS[source], f"{source} {field} {work_id}",
                f"{source}-{field}-{work_id}",
            ))
    return result


def work(row):
    return {
        "id": row["id"], "title": row["title"],
        "quality": {
            "band": "partial", "sentence": "Synthetic source comparison.",
            "evidence": [
                {
                    "signal": f"{field}_source", "verdict": row["verdicts"][field],
                    "direction": "neutral" if row["verdicts"][field] == quality.UNAVAILABLE
                    else "supports" if row["verdicts"][field] == quality.AGREE else "weakens",
                    "value": None,
                }
                for field in FIELDS
            ],
        },
        "source_comparison": comparison(row["id"], row["verdicts"], row["sources"]),
        "authors": [], "abstract": {"text": "", "reason": "not-in-source"},
        "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
        "topics": [], "doi": None, "oa": {"license": None, "url": None},
        "openalex_url": "", "year": 2020, "source": {"name": "OpenAlex venue"},
        "cited_by_count": 0, "in_corpus_cited_by": 0, "raw": f"oa-record-{row['id']}",
    }


def write_fixture(data):
    rows = [
        {"id": "W-AGREE", "title": "All sources agree", "sources": {
            field: ("crossref", "europepmc") for field in FIELDS
        }, "verdicts": field_verdicts(title=quality.AGREE, venue=quality.AGREE, date=quality.AGREE)},
        {"id": "W-CROSSREF-TITLE", "title": "Crossref title disagreement", "sources": {
            "title": ("crossref",)
        }, "verdicts": field_verdicts(title=quality.CROSSREF_DISAGREES)},
        {"id": "W-EUROPEPMC-TITLE", "title": "Europe PMC title disagreement", "sources": {
            "title": ("europepmc",)
        }, "verdicts": field_verdicts(title=quality.EUROPEPMC_DISAGREES)},
        {"id": "W-BOTH-VENUE", "title": "Both venue disagreements", "sources": {
            "venue": ("crossref", "europepmc")
        }, "verdicts": field_verdicts(venue=quality.BOTH_DISAGREE)},
        {"id": "W-CROSSREF-DATE", "title": "Crossref date disagreement", "sources": {
            "date": ("crossref",)
        }, "verdicts": field_verdicts(date=quality.CROSSREF_DISAGREES)},
        # This status is agreement overall, but Europe PMC supplied no title;
        # it must not become a Europe PMC agreement in the matrix.
        {"id": "W-CROSSREF-TITLE-AGREES", "title": "Crossref-only title agreement", "sources": {
            "title": ("crossref",)
        }, "verdicts": field_verdicts(title=quality.AGREE)},
        {"id": "W-UNAVAILABLE", "title": "No comparable assertions", "sources": {},
         "verdicts": field_verdicts()},
    ]
    index = [
        {"id": row["id"], "title": row["title"], "authors": [], "quality": "partial",
         "year": 2020, "cited": 0, "in_corpus_cited": 0, "n_authors": 0}
        for row in rows
    ]
    corpus = {
        "counts": {"works": len(rows), "authors": 0, "citations": 0,
                   "coauthor_edges": 0, "institutions": 0},
        "identity": {"high": 0, "medium": 0, "low": 0},
        "quality": {"complete": 0, "partial": len(rows), "suspect": 0},
        "definition": {"name": "Synthetic source matrix", "description": "Fixture corpus."},
        "abstracts": {}, "sources": [], "identity_notes": {},
        "identity_bands": {"high": "High.", "medium": "Medium.", "low": "Low."},
        "quality_notes": {},
    }
    (data / "authors").mkdir(parents=True)
    (data / "works").mkdir()
    (data / "corpus.json").write_text(json.dumps(corpus))
    (data / "authors-index.json").write_text("[]")
    (data / "works-index.json").write_text(json.dumps(index))
    (data / "payloads.json").write_text("{}")
    (data / "authors" / "fixture.json").write_text("{}")
    (data / "works" / "fixture.json").write_text(json.dumps({row["id"]: work(row) for row in rows}))


def matrix_rows(html):
    panel = re.search(
        r'<h2>Source record field comparisons</h2>.*?<tbody>(.*?)</tbody>', html, re.S,
    )
    if panel is None:
        return None
    # The disagreeing count is a link to that cohort's page; the route it points
    # at is pinned by test_methodology_disagreement_href.py.
    return re.findall(
        r'<tr><td>(.*?)</td><td>(.*?)</td><td class="num">(.*?)</td>'
        r'<td class="num">(.*?)</td><td class="num"><a href="[^"]+">(.*?)</a></td></tr>',
        panel.group(1),
    )


def main():
    bad = 0
    temporary = Path(tempfile.mkdtemp())
    saved = render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS
    try:
        data = temporary / "data"
        write_fixture(data)
        render.DATA = data
        render.SITE = temporary / "site"
        render.ASSETS = Path(__file__).parent / "web" / "assets"
        bad += check(render.main() == 0, "synthetic render failed")

        page = render.SITE / "methodology" / "index.html"
        html = page.read_text() if page.exists() else ""
        rows = matrix_rows(html)
        expected = {
            ("Crossref", "Title"): (3, 2, 1),
            ("Europe PMC", "Title"): (2, 1, 1),
            ("Crossref", "Venue"): (2, 1, 1),
            ("Europe PMC", "Venue"): (2, 1, 1),
            ("Crossref", "Publication date"): (2, 1, 1),
            ("Europe PMC", "Publication date"): (1, 1, 0),
        }
        bad += check(rows is not None, "methodology has no source-field comparison table")
        actual = {
            (source, field): tuple(int(value.replace(",", "")) for value in counts)
            for source, field, *counts in (rows or [])
        }
        bad += check(len(rows or []) == len(render.SOURCE_DISAGREEMENT_COHORTS),
                     "methodology does not render exactly six source-field rows")
        bad += check(actual == expected,
                     f"source-field counts are {actual!r}, expected {expected!r}")
        bad += check(
            all(comparable == agreeing + disagreeing
                for comparable, agreeing, disagreeing in actual.values()),
            "a source-field row does not satisfy comparable = agreeing + disagreeing",
        )
        bad += check(
            "unavailable for that source and field, so they are outside" in html
            and "Agreeing plus disagreeing always equals comparable." in html,
            "methodology does not explain unavailable records and additive totals",
        )
    finally:
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(temporary, ignore_errors=True)

    print("test_methodology_source_matrix:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
