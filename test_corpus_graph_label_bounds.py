#!/usr/bin/env python3
"""Keep every sampled committed graph's label boxes inside its viewBox."""
from __future__ import annotations

import sys

import render
from test_full_corpus_graph_fallback import populated_payloads


STRIDE = 15
HORIZONTAL_INSET = 4


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def sampled_payloads(kind: str):
    """A fixed stride over every populated graph, sorted by entity id.

    `populated_payloads` (test_full_corpus_graph_fallback.py) already walks
    shards in sorted order and filters to graphs with >= 2 nodes; sorting the
    full result by entity id before striding makes the sample independent of
    dict iteration order and reproducible run to run.
    """
    entries = sorted(populated_payloads(kind), key=lambda item: item[0])
    return entries[::STRIDE]


def assert_box_in_bounds(kind: str, entity_id: str, width: float, height: float,
                          pos: dict[str, float], node_id: str, short: str,
                          box: tuple[float, float, float, float]) -> int:
    bad = 0
    prefix = f"{kind} {entity_id} node {node_id}:"
    left, top, right, bottom = box
    bad += check(top >= 0, f"{prefix} label top {top} is above the viewBox")
    bad += check(bottom <= height, f"{prefix} label bottom {bottom} exceeds viewBox height {height}")

    # `label_boxes`'s left/right are pre-anchor extents; svg_graph clamps the
    # rendered x position inward once a centred label would cross an edge
    # (render.py:551-557). Mirror that anchoring to check the box a reader
    # actually sees.
    x = pos[node_id]
    half = len(short) * 2.7
    if x - half < HORIZONTAL_INSET:
        left, right = HORIZONTAL_INSET, HORIZONTAL_INSET + 2 * half
    elif x + half > width - HORIZONTAL_INSET:
        left, right = width - HORIZONTAL_INSET - 2 * half, width - HORIZONTAL_INSET

    bad += check(left >= 0, f"{prefix} label left {left} is left of the viewBox")
    bad += check(right <= width, f"{prefix} label right {right} exceeds viewBox width {width}")
    return bad


def main() -> int:
    bad = 0
    sampled_counts = {"work": 0, "author": 0}

    for kind in ("work", "author"):
        for entity_id, payload in sampled_payloads(kind):
            graph = payload["graph"]
            width, height = graph["width"], graph["height"]
            boxes = render.label_boxes(graph, focus=entity_id)
            if not boxes:
                continue
            sampled_counts[kind] += 1
            pos = {n["id"]: n["x"] for n in graph["nodes"]}
            for node_id, short, box in boxes:
                bad += assert_box_in_bounds(kind, entity_id, width, height, pos, node_id, short, box)

    bad += check(sampled_counts["work"] > 0, "sample included no work graphs")
    bad += check(sampled_counts["author"] > 0, "sample included no author graphs")

    print(
        "test_corpus_graph_label_bounds:",
        "FAILED" if bad else "ok",
        f"(works={sampled_counts['work']}, authors={sampled_counts['author']})",
    )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
