#!/usr/bin/env python3
"""A valid provenance source URL is one anchor whose href is the URL, exactly.

The check is made through an HTML parser rather than by string matching: what
matters is the URL a browser hands back from the attribute, not the bytes the
renderer wrote. A `"` in a stored URL must not end the href early, a `<` must
not open a tag, and an `&` must survive the round trip unchanged.
"""
import json
import sys
from html.parser import HTMLParser
from pathlib import Path

import render

DATA = Path(__file__).parent / "web" / "data"
SHA = "a" * 64
FETCHED = "2026-09-15T12:00:00+00:00"

BENIGN = "https://api.openalex.org/works/W2911964244"
# A URL for each metacharacter the ticket names, and one carrying all four in
# the shapes that break out of an unescaped attribute.
HOSTILE = (
    'https://source.example.test/?q="onmouseover="alert(1)',
    "https://source.example.test/?q=<script>alert(1)</script>",
    "https://api.openalex.org/works?filter=openalex_id%3AW1%7CW2&per-page=50&cursor=%2A",
    'https://source.example.test/?q="><script>alert(1)</script>&amp;next=two',
)
INVALID = (
    "javascript:alert(1)",
    "https://[unterminated",
    "https://source.example.test/has a space",
    "//source.example.test/records",
    None,
)


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


class Anchors(HTMLParser):
    """Every anchor's parsed href and text, plus every tag the markup opened."""

    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[dict] = []
        self.tags: list[str] = []
        self.in_anchor = False

    def handle_starttag(self, tag: str, attrs) -> None:
        self.tags.append(tag)
        if tag == "a":
            self.anchors.append({"attrs": dict(attrs), "text": ""})
            self.in_anchor = True

    def handle_data(self, data: str) -> None:
        if self.in_anchor:
            self.anchors[-1]["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.in_anchor = False


def parse(markup: str) -> Anchors:
    parser = Anchors()
    parser.feed(markup)
    parser.close()
    return parser


def rows_html(payloads: dict) -> str:
    return render.provenance_html(sorted(payloads), payloads)


def anchored_exactly(markup: str, url: str, context: str) -> int:
    """One anchor, its parsed href equal to the source URL, nothing injected.

    A URL may only ever change the row's text and attributes: the elements it
    opens must be exactly the ones the benign URL opens.
    """
    bad = 0
    parsed = parse(markup)
    bad += check(len(parsed.anchors) == 1,
                 f"{context}: expected exactly one anchor, found {len(parsed.anchors)}: {markup}")
    if parsed.anchors:
        href = parsed.anchors[0]["attrs"].get("href")
        bad += check(href == url,
                     f"{context}: parsed href {href!r} is not the source URL {url!r}")
        bad += check(parsed.anchors[0]["text"].strip() != "",
                     f"{context}: the anchor has no link text")
    reference = parse(rows_html({SHA: {"url": BENIGN, "fetched_at": FETCHED}}))
    bad += check(parsed.tags == reference.tags,
                 f"{context}: URL metacharacters became markup: {parsed.tags}")
    bad += check("<script" not in markup and 'onmouseover="' not in markup,
                 f"{context}: the raw URL reached the markup unescaped: {markup}")
    return bad


def work_page(url: str) -> str:
    """The work template around the row, so page-level wrapping is covered too."""
    work = {
        "id": "W1",
        "title": "Escaping fixture",
        "year": 2026,
        "date": "2026-09-15",
        "doi": None,
        "source": {"id": "S1", "name": "Fixture Journal"},
        "oa": {"url": None, "license": None},
        "abstract": {"text": "", "reason": "not-in-source"},
        "cited_by_count": 0,
        "in_corpus_cited_by": 0,
        "authors": [],
        "topics": [],
        "graph": {"width": 10, "height": 10, "nodes": [], "edges": [], "shown": 0, "available": 0},
        "quality": {"band": "complete", "sentence": "Complete", "evidence": []},
        "raw": SHA,
        "openalex_url": "https://openalex.org/W1",
    }
    return render.render_work(work, {}, {}, {SHA: {"url": url, "fetched_at": FETCHED}}, {}, set())


def main() -> int:
    bad = 0
    for url in (BENIGN,) + HOSTILE:
        bad += anchored_exactly(rows_html({SHA: {"url": url, "fetched_at": FETCHED}}), url, url)

    # Through the whole page: the one anchor pointing at the source must still
    # parse back to it once the row is inside the work template, and a hostile
    # URL must change the page's text, never its structure.
    benign_page, hostile_page = parse(work_page(BENIGN)), parse(work_page(HOSTILE[-1]))
    matching = [a for a in hostile_page.anchors if a["attrs"].get("href") == HOSTILE[-1]]
    bad += check(len(matching) == 1,
                 f"work page carries {len(matching)} anchors for the source URL, expected 1")
    bad += check(hostile_page.tags == benign_page.tags,
                 "a hostile source URL changed the work page's element structure")

    # Two payloads, two anchors, each href its own URL.
    two = {SHA: {"url": HOSTILE[0], "fetched_at": FETCHED},
           "b" * 64: {"url": BENIGN, "fetched_at": FETCHED}}
    hrefs = [a["attrs"].get("href") for a in parse(rows_html(two)).anchors]
    bad += check(hrefs == [HOSTILE[0], BENIGN],
                 f"two payloads rendered anchors {hrefs}, expected one each in hash order")

    # Anything that fails validation is never an anchor, and the hash and
    # fetch date it belongs to stay on the page.
    for url in INVALID:
        markup = rows_html({SHA: {"url": url, "fetched_at": FETCHED}})
        parsed = parse(markup)
        bad += check(not parsed.anchors,
                     f"invalid source URL rendered an anchor: {url!r} -> {markup}")
        bad += check(f"sha256 {SHA}" in markup and f"fetched {FETCHED}" in markup,
                     f"invalid source URL dropped the hash or fetch date: {url!r}")

    # The committed release: every exported source URL is linked, and each one
    # comes back out of its anchor unchanged.
    payloads = json.loads((DATA / "payloads.json").read_text(encoding="utf-8"))
    for sha, payload in sorted(payloads.items()):
        bad += anchored_exactly(rows_html({sha: payload}), payload.get("url"),
                                f"committed payload {sha}")

    print("test_provenance_url_escaping:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
