#!/usr/bin/env python3
"""Offline work-page rendering of the venue/work-type source-comparison panel."""
import re
import sys

import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def work(**changes):
    value = {
        "id": "W123",
        "title": "Complete work",
        "year": 2024,
        "date": "2024-02-03",
        "doi": "https://doi.org/10.1000/complete",
        "source": {"id": "S456", "name": "Source publication"},
        "oa": {"url": None, "license": None},
        "abstract": {"text": "", "reason": "no-abstract"},
        "cited_by_count": 4,
        "in_corpus_cited_by": 1,
        "authors": [],
        "topics": [],
        "graph": {"nodes": [], "shown": 0, "available": 0},
        "quality": {"band": "complete", "sentence": "Complete", "evidence": []},
        "raw": None,
        "openalex_url": "https://openalex.org/W123",
    }
    value.update(changes)
    return value


PAYLOADS = {
    "sha_openalex": {"fetched_at": "2026-01-01T00:00:00+00:00", "url": "file://openalex"},
    "sha_crossref": {"fetched_at": "2026-01-02T00:00:00+00:00", "url": "file://crossref"},
    "sha_europepmc": {"fetched_at": "2026-01-03T00:00:00+00:00", "url": "file://europepmc"},
}

COMPARISON = {
    "role": "Crossref is shown beside OpenAlex as a parallel observation of the same work; neither record is corrected by the other.",
    "venue": {
        "openalex": {"source": "OpenAlex", "value": "Journal of <Testing>", "raw": "sha_openalex"},
        "crossref": [{"source": "Crossref", "value": "J. Test.", "raw": "sha_crossref"}],
        "status": "agree",
    },
    "work_type": {
        "openalex": {"source": "OpenAlex", "value": "article", "raw": "sha_openalex"},
        "crossref": [],
        "status": "unavailable",
    },
    "title": {
        "openalex": {"source": "OpenAlex", "value": "Complete work", "raw": "sha_openalex"},
        "crossref": [{"source": "Crossref", "value": "Complete work", "raw": "sha_crossref"}],
        "europepmc": [{"source": "Europe PMC", "value": "A different title", "raw": "sha_europepmc"}],
        "status": "europepmc_disagrees",
    },
    "date": {
        "openalex": {"source": "OpenAlex", "value": "2024-02-03", "raw": "sha_openalex"},
        "crossref": [{"source": "Crossref", "value": "2020-01-01", "raw": "sha_crossref"}],
        "europepmc": [],
        "status": "crossref_disagrees",
        "precision": "day",
    },
}


def render_work(value):
    return render.render_work(value, {}, {}, PAYLOADS, {}, set())


def main() -> int:
    bad = 0

    page = render_work(work(source_comparison=COMPARISON))

    panel_match = re.search(
        r'<div class="panel">\s*<h2>Venue, work type, title and date across sources</h2>.*?</div>\n', page, re.S,
    )
    bad += check(panel_match is not None, "no source-comparison panel was rendered")
    panel = panel_match.group(0) if panel_match else ""

    # Both source values appear verbatim and HTML-escaped.
    bad += check("Journal of &lt;Testing&gt;" in panel, "OpenAlex venue value is not HTML-escaped in the panel")
    bad += check("J. Test." in panel, "Crossref venue value is missing from the panel")
    bad += check("<Testing>" not in panel, "OpenAlex venue value leaked unescaped markup")
    bad += check("article" in panel, "OpenAlex work-type value is missing from the panel")

    # Each source value carries its own hash and fetched timestamp.
    bad += check("sha256 sha_openalex" in panel and "2026-01-01T00:00:00+00:00" in panel,
                 "OpenAlex row is missing its own payload hash and fetch time")
    bad += check("sha256 sha_crossref" in panel and "2026-01-02T00:00:00+00:00" in panel,
                 "Crossref row is missing its own payload hash and fetch time")

    # The status badge classes match the exported statuses.
    bad += check('<span class="badge agree">agree</span>' in panel,
                 "the venue field's badge does not match its exported 'agree' status")
    bad += check('<span class="badge unavailable">unavailable</span>' in panel,
                 "the work_type field's badge does not match its exported 'unavailable' status")

    # Title and date carry the four-way verdict, and a Europe-PMC-only
    # disagreement is distinguishable from a Crossref-only one on the page.
    bad += check('<span class="badge europepmc_disagrees">europepmc_disagrees</span>' in panel,
                 "the title field's europepmc-only disagreement did not render as europepmc_disagrees")
    bad += check('<span class="badge crossref_disagrees">crossref_disagrees</span>' in panel,
                 "the date field's crossref-only disagreement did not render as crossref_disagrees")
    bad += check("A different title" in panel, "the Europe PMC title observation is missing from the panel")
    bad += check("sha256 sha_europepmc" in panel and "2026-01-03T00:00:00+00:00" in panel,
                 "the Europe PMC row is missing its own payload hash and fetch time")
    bad += check("compared to the day" in panel, "the date field's precision note is missing from the panel")

    # The exported role sentence heads the panel.
    bad += check(COMPARISON["role"] in panel, "the exported role sentence is missing from the panel")

    # A work without source_comparison renders cleanly, with no panel and no traceback.
    bare_page = render_work(work())
    bad += check("Venue, work type, title and date across sources" not in bare_page,
                 "a work with no source_comparison rendered the panel anyway")
    bad += check("<h1>Complete work</h1>" in bare_page,
                 "a work with no source_comparison failed to render the rest of the page")

    # web/assets/style.css defines the four new badge classes, plus the
    # three-way verdict classes title/date can carry once Europe PMC is folded in.
    css = open("web/assets/style.css").read()
    for badge_class in (
        "agree", "disagree", "unavailable", "incomparable",
        "crossref_disagrees", "europepmc_disagrees", "both_disagree",
    ):
        bad += check(f".badge.{badge_class}" in css, f"web/assets/style.css is missing .badge.{badge_class}")

    print("test_venue_type_render:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
