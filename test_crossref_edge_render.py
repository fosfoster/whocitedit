#!/usr/bin/env python3
"""Crossref as a recognised index in citation_edge_status and /methodology."""
import html
import sys

import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def main() -> int:
    bad = 0

    status, label = render.citation_edge_status({"sources": ["crossref"]})
    bad += check(
        status == "crossref-only" and label == "Crossref only — unconfirmed by OpenAlex",
        "a Crossref-only edge is not labelled crossref-only with the unconfirmed wording",
    )

    status, label = render.citation_edge_status({"sources": ["crossref", "openalex"]})
    bad += check(
        status == "corroborated" and "Crossref" in label and "OpenAlex" in label,
        "a Crossref+OpenAlex edge is not corroborated and naming both indexes",
    )

    status, label = render.citation_edge_status({"sources": ["crossref", "opencitations"]})
    bad += check(
        status == "corroborated" and "Crossref" in label and "OpenCitations" in label,
        "a Crossref+OpenCitations edge is not corroborated and naming both indexes",
    )

    status, label = render.citation_edge_status(
        {"sources": ["openalex", "opencitations", "crossref"]}
    )
    bad += check(
        status == "corroborated"
        and all(name in label for name in ("OpenAlex", "OpenCitations", "Crossref")),
        "a three-index edge including Crossref does not name all three indexes",
    )

    status, label = render.citation_edge_status({"sources": ["openalex", "opencitations"]})
    bad += check(
        status == "corroborated" and label == "Corroborated — OpenAlex and OpenCitations",
        "the existing OpenAlex+OpenCitations label changed",
    )

    status, label = render.citation_edge_status({"sources": []})
    bad += check(
        status == "legacy" and label == "Legacy edge — source detail unavailable",
        "an edge with no recognised source does not fall through to legacy",
    )

    corpus = {
        "abstracts": {},
        "sources": [],
        "identity": {"high": 0, "medium": 0, "low": 0},
        "quality": {"complete": 0, "partial": 0, "suspect": 0},
    }
    methodology = html.unescape(render.render_methodology(corpus))
    bad += check(
        "independently assert the same directed DOI-resolved edge" in methodology,
        "methodology does not state the two-or-more-index corroboration rule",
    )
    bad += check(
        "An edge asserted by only one index remains visible" in methodology,
        "methodology does not say that one-index edges remain visible",
    )
    bad += check(
        "Crossref" in methodology,
        "methodology does not mention Crossref as a recognised index",
    )

    print("test_crossref_edge_render:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
