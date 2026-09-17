#!/usr/bin/env python3
"""Work-page citation evidence and its documented interpretation."""
import html
import re
import sys

import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def work_page() -> str:
    nodes = [
        {"id": "W1", "label": "Focus", "kind": "focus", "cited": 10, "x": 100, "y": 100},
        {"id": "W2", "label": "Reference", "kind": "reference", "cited": 8, "x": 200, "y": 200},
        {"id": "W3", "label": "Citer", "kind": "citer", "cited": 6, "x": 300, "y": 100},
        {"id": "W4", "label": "Neighbour", "kind": "reference", "cited": 4, "x": 400, "y": 200},
        {"id": "W5", "label": "Biomedical", "kind": "reference", "cited": 3, "x": 500, "y": 200},
        {"id": "W6", "label": "Triple", "kind": "citer", "cited": 2, "x": 500, "y": 100},
    ]
    edges = [
        {"s": "W1", "t": "W2", "sources": ["openalex", "opencitations"]},
        {"s": "W3", "t": "W1", "sources": ["openalex"]},
        {"s": "W1", "t": "W4", "sources": ["opencitations"]},
        {"s": "W1", "t": "W5", "sources": ["europepmc"]},
        {"s": "W6", "t": "W1", "sources": ["europepmc", "openalex", "opencitations"]},
        {"s": "W6", "t": "W5", "sources": ["europepmc", "openalex"], "inner": True},
        {"s": "W2", "t": "W1", "sources": ["crossref"], "inner": True},
        {"s": "W5", "t": "W1", "sources": ["crossref", "europepmc"], "inner": True},
        # This neighbour-to-neighbour edge proves the evidence list is made
        # from all exported edges, rather than reconstructed from two tables.
        {"s": "W3", "t": "W2", "sources": [], "inner": True},
        {"s": "W4", "t": "W2", "inner": True},
    ]
    work = {
        "id": "W1",
        "title": "Evidence fixture",
        "year": 2026,
        "date": "2026-09-15",
        "doi": "https://doi.org/10.1000/evidence",
        "source": {"id": "S1", "name": "Fixture Journal"},
        "oa": {"url": None, "license": None},
        "abstract": {"text": "", "reason": "not-in-source"},
        "cited_by_count": 2,
        "in_corpus_cited_by": 1,
        "authors": [],
        "topics": [],
        "graph": {
            "width": 500,
            "height": 300,
            "nodes": nodes,
            "edges": edges,
            "shown": 3,
            "available": 3,
        },
        "quality": {"band": "complete", "sentence": "Complete", "evidence": []},
        "raw": None,
        "openalex_url": "https://openalex.org/W1",
    }
    return render.render_work(work, {}, {}, {}, {}, set())


def methodology_page() -> str:
    corpus = {
        "abstracts": {},
        "sources": [],
        "identity": {"high": 0, "medium": 0, "low": 0},
        "quality": {"complete": 0, "partial": 0, "suspect": 0},
    }
    return render.render_methodology(corpus)


def main() -> int:
    bad = 0
    page = work_page()
    rows = re.findall(
        r'<li data-citing="([^"]+)" data-cited="([^"]+)" '
        r'data-evidence-status="([^"]+)">(.*?)</li>',
        page,
        re.S,
    )
    evidence = {
        (html.unescape(citing), html.unescape(cited)): (status, html.unescape(body))
        for citing, cited, status, body in rows
    }
    expected_edges = {("W1", "W2"), ("W3", "W1"), ("W1", "W4"), ("W3", "W2"), ("W4", "W2"),
                      ("W1", "W5"), ("W6", "W1"), ("W6", "W5"), ("W2", "W1"), ("W5", "W1")}
    bad += check(set(evidence) == expected_edges,
                 "the evidence output does not represent every exported graph edge")
    bad += check(
        evidence.get(("W1", "W2"), (None, ""))[0] == "corroborated"
        and "Corroborated — OpenAlex and OpenCitations" in evidence[("W1", "W2")][1],
        "the two-index edge is not labelled corroborated",
    )
    bad += check(
        evidence.get(("W3", "W1"), (None, ""))[0] == "openalex-only"
        and "OpenAlex only" in evidence[("W3", "W1")][1],
        "the OpenAlex-only edge is not identified",
    )
    bad += check(
        evidence.get(("W1", "W4"), (None, ""))[0] == "opencitations-only"
        and "OpenCitations only — unconfirmed by OpenAlex" in evidence[("W1", "W4")][1],
        "the OpenCitations-only edge is not called unconfirmed by OpenAlex",
    )
    bad += check(
        evidence.get(("W1", "W5"), (None, ""))[0] == "europepmc-only"
        and "Europe PMC only" in evidence[("W1", "W5")][1],
        "the Europe PMC-only edge is not identified",
    )
    bad += check(
        evidence.get(("W6", "W1"), (None, ""))[0] == "corroborated"
        and all(name in evidence[("W6", "W1")][1]
                for name in ("OpenAlex", "OpenCitations", "Europe PMC")),
        "the three-index edge does not name all three corroborating indexes",
    )
    bad += check(
        evidence.get(("W6", "W5"), (None, ""))[0] == "corroborated"
        and "Corroborated — OpenAlex and Europe PMC" in evidence[("W6", "W5")][1],
        "a two-of-three edge is not labelled corroborated by the indexes that assert it",
    )
    bad += check(
        evidence.get(("W2", "W1"), (None, ""))[0] == "crossref-only"
        and "Crossref only" in evidence[("W2", "W1")][1],
        "the Crossref-only edge is not identified",
    )
    bad += check(
        evidence.get(("W5", "W1"), (None, ""))[0] == "corroborated"
        and "Corroborated — Europe PMC and Crossref" in evidence[("W5", "W1")][1],
        "the Crossref/Europe PMC edge is not labelled corroborated by both",
    )
    for edge in (("W3", "W2"), ("W4", "W2")):
        bad += check(
            evidence.get(edge, (None, ""))[0] == "legacy"
            and "Legacy edge — source detail unavailable" in evidence[edge][1],
            f"legacy edge {edge} does not explain that source detail is unavailable",
        )

    island_end = page.find("</figure>")
    evidence_start = page.find('<section class="edge-evidence"')
    bad += check(island_end >= 0 and evidence_start > island_end,
                 "citation evidence is inside the progressively enhanced graph island")

    methodology = html.unescape(methodology_page())
    bad += check(
        "independently assert the same directed DOI-resolved edge" in methodology,
        "methodology does not define the corroboration rule",
    )
    bad += check(
        all(name in methodology for name in ("OpenAlex", "OpenCitations", "Europe PMC")),
        "methodology does not name all three citation indexes in the corroboration rule",
    )
    bad += check(
        "An edge asserted by only one index remains visible" in methodology,
        "methodology does not say that one-index edges remain visible",
    )

    print("test_citation_render:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
