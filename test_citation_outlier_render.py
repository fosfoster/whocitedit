#!/usr/bin/env python3
"""Citation-count outlier warnings are static, escaped, and outside quality."""
from pathlib import Path
import sys

import render


ROOT = Path(__file__).parent


def check(condition, message):
    if condition:
        return 0
    print(f"  FAIL: {message}")
    return 1


def work(**changes):
    value = {
        "id": "W123",
        "title": "Fixture work",
        "year": 2020,
        "date": "2020-01-01",
        "doi": None,
        "source": {"id": "S1", "name": "Fixture venue"},
        "oa": {"url": None, "license": None},
        "abstract": {"text": None, "reason": "not-in-source"},
        "cited_by_count": 10000,
        "in_corpus_cited_by": 0,
        "authors": [],
        "topics": [],
        "graph": {"nodes": [], "shown": 0, "available": 0},
        "quality": {
            "band": "complete",
            "sentence": "Nothing in this record contradicts itself and no field we check is missing.",
            "evidence": [],
        },
        "raw": None,
        "openalex_url": "https://openalex.org/W123",
    }
    value.update(changes)
    return value


def render_work(value):
    return render.render_work(value, {}, {}, {}, {}, set())


def main() -> int:
    bad = 0
    quality = work()["quality"]
    evidence = {
        "observed_openalex_citation_count": 10000,
        "year": 2020,
        "venue": {"id": "S1", "name": "Venue <unsafe> & peers"},
        "peer_count": 9,
        "peer_median": 10,
        "effective_threshold": 50,
    }
    page = render_work(work(citation_count_outlier=evidence))

    bad += check('class="citation-outlier-warning"' in page and 'role="alert"' in page,
                 "outlier evidence did not render as a dedicated accessible warning")
    bad += check("The reported citation count is <b>10,000</b>." in page,
                 "warning omitted the reported citation count")
    bad += check("<b>2020</b> in <b>Venue &lt;unsafe&gt; &amp; peers</b>" in page,
                 "warning omitted or failed to escape its exact year-and-venue cohort")
    bad += check("<b>9</b> other works selected into this corpus" in page
                 and "peer median is\n  <b>10</b> citations" in page
                 and "threshold of <b>50</b>" in page,
                 "warning omitted the peer evidence")
    bad += check("only works selected into this corpus, not the wider population" in page,
                 "warning did not limit its comparison to the selected corpus")
    bad += check("warning, not a correction: the source record remains unaltered" in page,
                 "warning did not say it leaves the source record unaltered")
    bad += check(
        '<span class="badge complete">complete</span></p>\n    <p>'
        + quality["sentence"] + "</p>" in page,
        "citation warning changed the existing quality badge or sentence",
    )

    ordinary = render_work(work())
    bad += check("citation-outlier-warning" not in ordinary,
                 "work without outlier evidence rendered a warning")
    css = (ROOT / "web" / "assets" / "style.css").read_text()
    bad += check(".citation-outlier-warning" in css,
                 "warning styling class is missing from the static stylesheet")

    print("test_citation_outlier_render:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
