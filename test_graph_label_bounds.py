#!/usr/bin/env python3
"""Keep static-SVG label boxes from crossing the graph's top and bottom edges."""
import sys

import render


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def edge_graph():
    """A tiny graph with nodes hugging the top and bottom viewBox edges.

    Labels are 30 chars, the render.py cutoff for keeping the full title, so
    every node here gets a label. `blocker` forces `bot`'s greedy placement to
    fall back to the below-node slot, which is the slot that overshoots the
    bottom edge -- matching the real graphs in the evidence where a label
    collision pushes the fallback slot past the boundary.
    """
    return {
        "width": 400,
        "height": 120,
        "nodes": [
            {"id": "top", "x": 100, "y": 6, "label": "A" * 30, "kind": "coauthor", "cited": 500},
            {"id": "blocker", "x": 300, "y": 114, "label": "B" * 30, "kind": "coauthor", "cited": 500},
            {"id": "bot", "x": 300, "y": 114, "label": "C" * 30, "kind": "coauthor", "cited": 500},
        ],
        "edges": [],
    }


def degenerate_graph():
    """A viewBox too short to fit the box plus both insets."""
    return {
        "width": 200,
        "height": 10,
        "nodes": [
            {"id": "only", "x": 100, "y": 5, "label": "D" * 30, "kind": "coauthor", "cited": 1},
        ],
        "edges": [],
    }


def main() -> int:
    bad = 0

    g = edge_graph()
    boxes = render.label_boxes(g)
    kept = {node_id: box for node_id, _short, box in boxes}

    bad += check(len(kept) == 3, f"expected all three labels kept, got {sorted(kept)}")

    for node_id, box in kept.items():
        left, top, right, bottom = box
        bad += check(top >= 0, f"{node_id} label top {top} is above the viewBox (y=0)")
        bad += check(
            bottom <= g["height"],
            f"{node_id} label bottom {bottom} exceeds viewBox height {g['height']}",
        )

    # The clamp must not have papered over the fallback logic: boxes still
    # must not overlap each other.
    values = list(kept.values())
    for i, a in enumerate(values):
        for b in values[i + 1:]:
            overlap = a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
            bad += check(not overlap, f"clamped label boxes overlap: {a} vs {b}")

    dg = degenerate_graph()
    dboxes = render.label_boxes(dg)
    for node_id, _short, box in dboxes:
        left, top, right, bottom = box
        bad += check(top <= bottom, f"{node_id} degenerate box inverted: {box}")
        bad += check(top >= 0, f"{node_id} degenerate box top {top} is negative")

    print("test_graph_label_bounds:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
