#!/usr/bin/env python3
"""svg_graph tags corroborated citation edges without touching other kinds."""
import re
import sys

import render


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def edge_graph():
    nodes = [
        {"id": "A", "x": 10, "y": 10, "label": "A", "kind": "focus", "cited": 10},
        {"id": "B", "x": 100, "y": 10, "label": "B", "kind": "reference", "cited": 5},
        {"id": "C", "x": 10, "y": 100, "label": "C", "kind": "reference", "cited": 5},
        {"id": "D", "x": 100, "y": 100, "label": "D", "kind": "reference", "cited": 5},
        {"id": "E", "x": 200, "y": 10, "label": "E", "kind": "reference", "cited": 5},
        {"id": "F", "x": 200, "y": 100, "label": "F", "kind": "reference", "cited": 5},
    ]
    edges = [
        # two-index: corroborated
        {"s": "A", "t": "B", "sources": ["openalex", "opencitations"]},
        # three-index: corroborated
        {"s": "A", "t": "C", "sources": ["openalex", "opencitations", "europepmc"]},
        # one-index: not corroborated
        {"s": "A", "t": "D", "sources": ["openalex"]},
        # empty sources: not corroborated
        {"s": "A", "t": "E", "sources": []},
        # no sources key: not corroborated (legacy)
        {"s": "A", "t": "F", "w": 2.0},
        # corroborated inner edge
        {"s": "B", "t": "C", "sources": ["openalex", "crossref"], "inner": True},
    ]
    return {"width": 300, "height": 150, "nodes": nodes, "edges": edges}


def line_classes(markup):
    return re.findall(r'<line class="([^"]*)"', markup)


def main() -> int:
    bad = 0

    g = edge_graph()
    markup = render.svg_graph(g, {}, "Citation edges", kind="citation")
    classes = line_classes(markup)
    bad += check(len(classes) == len(g["edges"]), f"expected {len(g['edges'])} lines, got {len(classes)}")

    # order matches g["edges"] insertion order
    expected = [
        "edge corroborated",   # A-B two-index
        "edge corroborated",   # A-C three-index
        "edge",                # A-D one-index
        "edge",                # A-E empty sources
        "edge",                # A-F no sources key
        "edge inner corroborated",  # B-C corroborated inner
    ]
    bad += check(classes == expected, f"citation edge classes {classes} != {expected}")

    bad += check(
        'stroke-width="' in markup,
        "stroke-width attribute missing from citation edges",
    )

    collab_markup = render.svg_graph(g, {}, "Collaboration edges", kind="collaboration")
    collab_classes = line_classes(collab_markup)
    bad += check(
        all("corroborated" not in cls for cls in collab_classes),
        f"collaboration graph emitted a corroborated token: {collab_classes}",
    )
    bad += check(
        collab_classes == ["edge", "edge", "edge", "edge", "edge", "edge inner"],
        f"collaboration edge classes changed shape: {collab_classes}",
    )

    print("test_svg_citation_edge_corroboration:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
