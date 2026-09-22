#!/usr/bin/env python3
"""Offline coverage for all six uncapped source-disagreement cohorts."""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import export_json
import quality
import render
import test_full_corpus_render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


FIELDS = ("title", "venue", "date")


def assertion(source, value, raw):
    return {"source": source, "value": value, "raw": raw}


def verdicts(**overrides):
    return {field: overrides.get(field, quality.UNAVAILABLE) for field in FIELDS}


def evidence(field_verdicts):
    return [
        {
            "signal": f"{field}_source",
            "verdict": field_verdicts[field],
            "direction": (
                "neutral" if field_verdicts[field] == quality.UNAVAILABLE
                else "supports" if field_verdicts[field] == quality.AGREE
                else "weakens"
            ),
            "value": None,
        }
        for field in FIELDS
    ]


def source_comparison(work_id, field_verdicts):
    comparison = {"role": "Synthetic parallel observations; neither source corrects another."}
    for field in FIELDS:
        verdict = field_verdicts[field]
        block = {
            "openalex": assertion(
                "OpenAlex", f"OpenAlex {field} for {work_id}", f"sha-openalex-{field}-{work_id}",
            ),
            "crossref": [],
            "europepmc": [],
            "status": verdict,
        }
        if verdict in (quality.CROSSREF_DISAGREES, quality.BOTH_DISAGREE, quality.AGREE):
            block["crossref"].append(assertion(
                "Crossref", f"Crossref {field} for {work_id}", f"sha-crossref-{field}-{work_id}",
            ))
        if verdict in (quality.EUROPEPMC_DISAGREES, quality.BOTH_DISAGREE, quality.AGREE):
            block["europepmc"].append(assertion(
                "Europe PMC", f"Europe PMC {field} for {work_id}", f"sha-europepmc-{field}-{work_id}-1",
            ))
        comparison[field] = block
    if work_id == "W-BOTH-VENUE":
        comparison["venue"]["europepmc"].append(assertion(
            "Europe PMC",
            "Second Europe PMC venue for W-BOTH-VENUE",
            "sha-europepmc-venue-W-BOTH-VENUE-2",
        ))
    return comparison


def work_detail(row, field_verdicts):
    return {
        "id": row["id"], "title": row["title"],
        "quality": {
            "band": row["quality"], "sentence": "Synthetic fixture.",
            "evidence": evidence(field_verdicts),
        },
        "source_comparison": source_comparison(row["id"], field_verdicts),
        "authors": [], "abstract": {"text": "", "reason": "not-in-source"},
        "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
        "topics": [], "doi": None, "oa": {"license": None, "url": None},
        "openalex_url": "", "year": 2020, "source": {"name": "OpenAlex venue"},
        "cited_by_count": row["cited"], "in_corpus_cited_by": 0,
        "raw": f'sha-openalex-record-{row["id"]}',
    }


def write_fixture(data: Path):
    large_cohort = [
        {
            "id": f"W-TITLE-CROSSREF-{number:03d}",
            "title": f"Crossref title disagreement {number:03d}",
            "verdicts": verdicts(title=quality.CROSSREF_DISAGREES),
        }
        for number in range(401)
    ]
    special = [
        {"id": "W-AGREE", "title": "All sources agree", "verdicts": verdicts(
            title=quality.AGREE, venue=quality.AGREE, date=quality.AGREE,
        )},
        {"id": "W-BOTH-TITLE", "title": "Both titles disagree", "verdicts": verdicts(
            title=quality.BOTH_DISAGREE,
        )},
        {"id": "W-EUROPEPMC-TITLE", "title": "Europe PMC title disagrees", "verdicts": verdicts(
            title=quality.EUROPEPMC_DISAGREES,
        )},
        {"id": "W-BOTH-VENUE", "title": "Both venues disagree", "verdicts": verdicts(
            venue=quality.BOTH_DISAGREE,
        )},
        {"id": "W-CROSSREF-DATE", "title": "Crossref date disagrees", "verdicts": verdicts(
            date=quality.CROSSREF_DISAGREES,
        )},
        {"id": "W-UNAVAILABLE", "title": "No comparable assertions", "verdicts": verdicts()},
    ]
    # Deliberately interleave membership so an implementation that renders in
    # shard or cohort-discovery order cannot accidentally pass the order check.
    definitions = [special[0], large_cohort[0], special[1], *large_cohort[1:200],
                   special[2], special[3], *large_cohort[200:], special[4], special[5]]
    works = []
    details = {}
    for number, definition in enumerate(definitions):
        row = {
            "id": definition["id"], "title": definition["title"], "authors": [],
            "quality": "partial", "year": 2020, "cited": number,
            "in_corpus_cited": 0, "n_authors": 0,
        }
        works.append(row)
        details[row["id"]] = work_detail(row, definition["verdicts"])

    corpus = {
        "counts": {"works": len(works), "authors": 0, "citations": 0,
                   "coauthor_edges": 0, "institutions": 0},
        "identity": {"high": 0, "medium": 0, "low": 0},
        "quality": {"complete": 0, "partial": len(works), "suspect": 0},
        "definition": {"name": "Synthetic source cohorts", "description": "Fixture corpus."},
        "abstracts": {}, "sources": [], "identity_notes": {},
        "identity_bands": {"high": "High.", "medium": "Medium.", "low": "Low."},
        "quality_notes": {},
    }
    (data / "authors").mkdir(parents=True)
    (data / "works").mkdir()
    (data / "corpus.json").write_text(json.dumps(corpus))
    (data / "authors-index.json").write_text("[]")
    (data / "works-index.json").write_text(json.dumps(works))
    (data / "payloads.json").write_text("{}")
    (data / "authors" / "fixture.json").write_text("{}")
    (data / "works" / "fixture.json").write_text(json.dumps(details))
    return works, details


def cohort_ids(html):
    return re.findall(r'href="\.\./\.\./\.\./w/([^/"]+)/"', html)


def exported_venue_assertions_are_complete():
    europepmc_rows = [
        {"raw_sha": "sha-venue-one", "title": "Title one", "venue": "Venue one",
         "venue_short": "V1", "publication_date": "2020-01-01"},
        {"raw_sha": "sha-venue-two", "title": "Title two", "venue": None,
         "venue_short": "Venue two short", "publication_date": "2020-01-02"},
    ]

    class Connection:
        class Cursor:
            def __init__(self, rows):
                self.rows = rows

            def fetchall(self):
                return self.rows

        def execute(self, query, _params):
            rows = europepmc_rows if "europepmc_work_assertion" in query else []
            return self.Cursor(rows)

    comparison = export_json._source_comparison(
        Connection(), "W1", "OpenAlex venue", "article", "sha-openalex",
        "OpenAlex title", "2020-01-01",
    )
    return comparison["venue"].get("europepmc") == [
        assertion("Europe PMC", "Venue one", "sha-venue-one"),
        assertion("Europe PMC", "Venue two short", "sha-venue-two"),
    ]


def main() -> int:
    bad = check(
        exported_venue_assertions_are_complete(),
        "source_comparison did not preserve every Europe PMC venue value and raw sha",
    )
    temporary = Path(tempfile.mkdtemp())
    saved = render.DATA, render.SITE, render.ASSETS
    try:
        data = temporary / "data"
        works, details = write_fixture(data)
        render.DATA = data
        render.SITE = temporary / "site"
        render.ASSETS = Path(__file__).parent / "web" / "assets"
        bad += check(render.main() == 0, "synthetic render failed")

        sitemap = (render.SITE / "sitemap.xml").read_text()
        comparable_totals = {
            ("title", "crossref"): 403,
            ("title", "europepmc"): 3,
            ("venue", "crossref"): 2,
            ("venue", "europepmc"): 2,
            ("date", "crossref"): 2,
            ("date", "europepmc"): 1,
        }
        for (field, source), config in render.SOURCE_DISAGREEMENT_COHORTS.items():
            route = config["path"].rstrip("/")
            page = render.SITE / route / "index.html"
            bad += check(page.exists(), f"missing /{route}/")
            if not page.exists():
                continue
            html = page.read_text()
            expected = [
                row["id"] for row in works
                if render.disagrees_with(details[row["id"]], field, source)
            ]
            comparable = comparable_totals[(field, source)]
            bad += check(cohort_ids(html) == expected,
                         f"/{route}/ membership or works-index order is wrong")
            bad += check(f"{len(expected):,} of {comparable:,} comparable works" in html,
                         f"/{route}/ does not print its member and comparable-work totals")
            bad += check(html.count("<tbody>") == 1 and html.count("<tr>") == len(expected) + 1,
                         f"/{route}/ does not render one table row per member")
            for work_id in expected:
                bad += check((render.SITE / "w" / work_id / "index.html").exists(),
                             f"/{route}/ links missing work page for {work_id}")
                row = re.search(rf'<tr>.*?href="\.\./\.\./\.\./w/{re.escape(work_id)}/".*?</tr>', html, re.S)
                bad += check(row is not None, f"/{route}/ has no row for {work_id}")
                row_html = row.group(0) if row else ""
                for observation in render.source_observations(details[work_id], field, source):
                    bad += check(str(observation["value"]) in row_html,
                                 f"/{route}/ {work_id} omits {observation['value']!r}")
                    bad += check(f"sha256 {observation['raw']}" in row_html,
                                 f"/{route}/ {work_id} omits sha256 {observation['raw']}")
            bad += check(f"/{config['path']}" in sitemap, f"/{route}/ missing from sitemap")
            bad += check(f"{config['path']}index.html" in test_full_corpus_render.FIXED_HTML_ROUTES,
                         f"/{route}/ missing from FIXED_HTML_ROUTES")
            if not expected:
                bad += check("No works in this release match this disagreement cohort." in html,
                             f"/{route}/ empty cohort has no explicit empty-state copy")

        large_route = render.SITE / "works/title-disagreement/crossref/index.html"
        if large_route.exists():
            bad += check(len(cohort_ids(large_route.read_text())) > 400,
                         "large disagreement fixture did not prove the cohort is uncapped")
        venue_route = render.SITE / "works/venue-disagreement/europepmc/index.html"
        if venue_route.exists():
            venue_page = venue_route.read_text()
            for value, raw in (
                ("Europe PMC venue for W-BOTH-VENUE", "sha-europepmc-venue-W-BOTH-VENUE-1"),
                ("Second Europe PMC venue for W-BOTH-VENUE", "sha-europepmc-venue-W-BOTH-VENUE-2"),
            ):
                bad += check(value in venue_page and f"sha256 {raw}" in venue_page,
                             f"Europe PMC venue cohort omitted {value!r} or its sha256")
    finally:
        render.DATA, render.SITE, render.ASSETS = saved
        shutil.rmtree(temporary, ignore_errors=True)

    print("test_source_disagreement_cohorts:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
