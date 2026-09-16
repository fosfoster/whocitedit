#!/usr/bin/env python3
"""Direct work-page coverage for declared normalized field memberships."""
import html
import re
import sys

import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def work(fields):
    return {
        "id": "W123",
        "title": "Field fixture",
        "year": 2024,
        "date": None,
        "doi": None,
        "source": {"id": None, "name": None},
        "oa": {"url": None, "license": None},
        "abstract": {"text": None, "reason": "not-in-source"},
        "cited_by_count": 0,
        "in_corpus_cited_by": 0,
        "authors": [],
        "topics": [],
        "fields": fields,
        "graph": {"nodes": [], "shown": 0, "available": 0},
        "quality": {"band": "complete", "sentence": "Complete", "evidence": []},
        "raw": None,
        "openalex_url": "https://openalex.org/W123",
    }


def render_work(fields):
    return render.render_work(work(fields), {}, {}, {}, {}, set())


def membership_links(page):
    sections = re.findall(
        r'<section class="field-memberships" aria-labelledby="field-memberships-heading">(.*?)</section>',
        page,
        re.S,
    )
    if len(sections) != 1:
        return sections, []
    return sections, [
        (html.unescape(href), html.unescape(label))
        for href, label in re.findall(r'<a href="([^"]+)">(.*?)</a>', sections[0], re.S)
    ]


def main() -> int:
    bad = 0
    saved = render.NAV_FIELDS
    try:
        render.NAV_FIELDS = [
            {"key": "alpha", "name": "Alpha Field"},
            {"key": "zeta", "name": "Zeta Field"},
        ]
        two_field_page = render_work(["alpha", "zeta"])
        sections, links = membership_links(two_field_page)
        bad += check(len(sections) == 1, "two-field work has no single labeled membership section")
        bad += check(links == [
            ("../../fields/alpha/", "Alpha Field"),
            ("../../fields/zeta/", "Zeta Field"),
        ], "two-field memberships do not retain exported order, labels, and hrefs")
        bad += check(
            '<link rel="canonical" href="https://whocitedit.com/w/W123">' in two_field_page,
            "field memberships changed the canonical work URL",
        )

        single_field_page = render_work(["alpha"])
        sections, links = membership_links(single_field_page)
        bad += check(len(sections) == 1, "single-field work has no membership section")
        bad += check(links == [("../../fields/alpha/", "Alpha Field")],
                     "single-field work includes a non-member or wrong link")
        bad += check("../../fields/zeta/" not in sections[0] if sections else False,
                     "single-field membership section includes zeta")

        hostile_key = 'alpha\"><img src=x onerror="alert(1)">'
        hostile_label = 'Alpha <img src=x onerror="alert(1)">'
        render.NAV_FIELDS = [{"key": hostile_key, "name": hostile_label}]
        hostile_page = render_work([hostile_key])
        sections, links = membership_links(hostile_page)
        bad += check(len(sections) == 1 and links == [
            (f"../../fields/{hostile_key}/", hostile_label),
        ], "hostile field key or label did not round-trip through the membership link")
        bad += check("<img src=x" not in hostile_page and 'onerror="alert(1)"' not in hostile_page,
                     "hostile field metadata created markup")
    finally:
        render.NAV_FIELDS = saved

    print("test_work_field_links:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
