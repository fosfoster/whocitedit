#!/usr/bin/env python3
"""Citation-edge assertion rows stay with their exported directed edge."""
from __future__ import annotations

import re
import sys
from html.parser import HTMLParser

import render


OPENALEX = "a" * 64
CROSSREF = "b" * 64
UNSAFE = "c" * 64
ABSENT = "d" * 64
HASH = re.compile(r"sha256 ([0-9a-f]{64})")


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


class EdgeEvidence(HTMLParser):
    """Read edge items and their nested assertion rows without regex nesting."""

    def __init__(self):
        super().__init__()
        self.edges = {}
        self.edge = None
        self.in_status = False
        self.in_assertions = False
        self.assertion = None
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "li" and "data-citing" in attributes:
            self.edge = (attributes["data-citing"], attributes["data-cited"])
            self.edges[self.edge] = {
                "status": attributes["data-evidence-status"], "status_text": [], "assertions": [],
            }
        elif tag == "span" and self.edge and "edge-status" in (attributes.get("class") or "").split():
            self.in_status = True
        elif tag == "ul" and "edge-assertion-list" in (attributes.get("class") or "").split():
            self.in_assertions = True
        elif tag == "li" and self.in_assertions:
            self.assertion = {"text": [], "anchors": []}
        elif tag == "a" and self.assertion is not None:
            self.anchor = {"href": attributes.get("href"), "text": []}
            self.assertion["anchors"].append(self.anchor)

    def handle_data(self, data):
        if self.in_status and self.edge:
            self.edges[self.edge]["status_text"].append(data)
        if self.assertion is not None:
            self.assertion["text"].append(data)
        if self.anchor is not None:
            self.anchor["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "span" and self.in_status:
            self.in_status = False
        elif tag == "a" and self.anchor is not None:
            self.anchor["text"] = " ".join("".join(self.anchor["text"]).split())
            self.anchor = None
        elif tag == "li" and self.assertion is not None:
            self.assertion["text"] = " ".join("".join(self.assertion["text"]).split())
            self.edges[self.edge]["assertions"].append(self.assertion)
            self.assertion = None
        elif tag == "ul" and self.in_assertions:
            self.in_assertions = False
        elif tag == "li" and self.edge:
            self.edges[self.edge]["status_text"] = " ".join(
                "".join(self.edges[self.edge]["status_text"]).split()
            )
            self.edge = None


def rendered_page() -> str:
    nodes = [
        {"id": "W1", "label": "Focus", "kind": "focus", "cited": 10, "x": 100, "y": 100},
        {"id": "W2", "label": "Reference", "kind": "reference", "cited": 8, "x": 200, "y": 200},
        {"id": "W3", "label": "Citer", "kind": "citer", "cited": 6, "x": 300, "y": 100},
        {"id": "W4", "label": "Legacy", "kind": "reference", "cited": 4, "x": 400, "y": 200},
    ]
    work = {
        "id": "W1", "title": "Assertion fixture", "year": 2026, "date": None,
        "doi": None, "source": {"id": "S1", "name": "Fixture Journal"},
        "oa": {"url": None, "license": None},
        "abstract": {"text": "", "reason": "not-in-source"},
        "cited_by_count": 2, "in_corpus_cited_by": 1, "authors": [], "topics": [],
        "graph": {
            "width": 500, "height": 300, "nodes": nodes, "shown": 3, "available": 3,
            "edges": [
                {"s": "W1", "t": "W2", "sources": ["openalex", "crossref"], "assertions": [
                    {"source": "openalex", "raw": OPENALEX},
                    {"source": "crossref", "raw": CROSSREF},
                ]},
                {"s": "W3", "t": "W1", "sources": ["openalex"], "assertions": [
                    {"source": "openalex", "raw": UNSAFE},
                ]},
                {"s": "W2", "t": "W3", "sources": ["europepmc"], "inner": True, "assertions": [
                    {"source": "europepmc", "raw": ABSENT},
                ]},
                {"s": "W1", "t": "W4", "sources": [], "assertions": []},
            ],
        },
        "quality": {"band": "complete", "sentence": "Complete", "evidence": []},
        "raw": None, "openalex_url": "https://openalex.org/W1",
    }
    payloads = {
        OPENALEX: {"url": "https://api.openalex.org/works/W1", "fetched_at": "2026-09-01T01:02:03+00:00"},
        CROSSREF: {"url": "https://api.crossref.org/works/10.1/x", "fetched_at": "2026-09-02T04:05:06+00:00"},
        UNSAFE: {"url": "javascript:alert(1)", "fetched_at": "2026-09-03T07:08:09+00:00"},
    }
    return render.render_work(work, {}, {}, payloads, {}, set())


def assertion_hash(row):
    match = HASH.search(row["text"])
    return match.group(1) if match else None


def main() -> int:
    bad = 0
    parser = EdgeEvidence()
    parser.feed(rendered_page())
    parser.close()
    edges = parser.edges

    expected = {("W1", "W2"), ("W3", "W1"), ("W2", "W3"), ("W1", "W4")}
    bad += check(set(edges) == expected, "the rendered evidence does not contain one item per exported edge")

    corroborated = edges.get(("W1", "W2"), {})
    bad += check(
        corroborated.get("status") == "corroborated"
        and corroborated.get("status_text") == "Corroborated — OpenAlex and Crossref",
        "the multi-source edge did not keep its one corroborated status",
    )
    bad += check(
        [(assertion_hash(row), row["text"]) for row in corroborated.get("assertions", [])]
        == [
            (OPENALEX, f"OpenAlex: sha256 {OPENALEX} fetched 2026-09-01T01:02:03+00:00"),
            (CROSSREF, f"Crossref: sha256 {CROSSREF} fetched 2026-09-02T04:05:06+00:00"),
        ],
        "the corroborated edge did not render both exported assertions exactly once",
    )
    for row, url in zip(corroborated.get("assertions", []), (
        "https://api.openalex.org/works/W1", "https://api.crossref.org/works/10.1/x",
    )):
        bad += check(
            len(row["anchors"]) == 1 and row["anchors"][0]["href"] == url
            and row["anchors"][0]["text"] == f"sha256 {assertion_hash(row)}",
            f"the assertion for {assertion_hash(row)} was not linked to its stored source URL",
        )

    single = edges.get(("W3", "W1"), {})
    bad += check(single.get("status") == "openalex-only" and len(single.get("assertions", [])) == 1,
                 "the single-source assertion detached from its directed endpoints")
    if single.get("assertions"):
        row = single["assertions"][0]
        bad += check(
            assertion_hash(row) == UNSAFE and "OpenAlex" in row["text"]
            and "fetched 2026-09-03T07:08:09+00:00" in row["text"] and row["anchors"] == [],
            "an unsafe URL linked or suppressed the single-source assertion hash",
        )

    inner = edges.get(("W2", "W3"), {})
    bad += check(inner.get("status") == "europepmc-only" and len(inner.get("assertions", [])) == 1,
                 "the inner-neighbour assertion detached from its directed endpoints")
    if inner.get("assertions"):
        row = inner["assertions"][0]
        bad += check(
            assertion_hash(row) == ABSENT and "Europe PMC" in row["text"]
            and "fetched unknown" in row["text"] and row["anchors"] == [],
            "an absent payload URL linked or suppressed the inner-edge assertion hash",
        )

    legacy = edges.get(("W1", "W4"), {})
    bad += check(
        legacy.get("status") == "legacy"
        and legacy.get("status_text") == "Legacy edge — source detail unavailable"
        and legacy.get("assertions") == [],
        "the assertion-free legacy edge changed status or fabricated provenance",
    )

    print("test_citation_assertion_render:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
