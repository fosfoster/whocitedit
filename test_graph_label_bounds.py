#!/usr/bin/env python3
"""Keep final static-SVG label geometry inside every feasible graph edge."""
import sys

import render


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def edge_graph():
    """A tiny graph with nodes hugging all four viewBox edges.

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
            {"id": "left", "x": 6, "y": 60, "label": "L" * 30, "kind": "coauthor", "cited": 500},
            {"id": "right", "x": 394, "y": 60, "label": "R" * 30, "kind": "coauthor", "cited": 500},
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


def edge_collision_graph():
    """Edge anchoring makes the first candidate boxes overlap horizontally."""
    return {
        "width": 253,
        "height": 120,
        "nodes": [
            {"id": "left", "x": 6, "y": 60, "label": "L" * 30, "kind": "coauthor", "cited": 1},
            {"id": "right", "x": 247, "y": 60, "label": "R" * 30, "kind": "coauthor", "cited": 1},
        ],
        "edges": [],
    }


def fractional_graph():
    return {
        "width": 400,
        "height": 120,
        "nodes": [
            {"id": "fractional", "x": 100.25, "y": 60.04, "label": "fractional", "kind": "coauthor", "cited": 1},
            {"id": "other", "x": 300, "y": 60, "label": "other", "kind": "coauthor", "cited": 1},
        ],
        "edges": [],
    }


def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def check_contract(g, placements):
    """Assert each final box is implied by its exposed x/y/anchor."""
    bad = 0
    markup = render.svg_graph(g, {}, "Label bounds")
    for placement in placements:
        half = len(placement.text) * 2.7
        if placement.anchor == "start":
            left, right = placement.x, placement.x + 2 * half
        elif placement.anchor == "end":
            left, right = placement.x - 2 * half, placement.x
        else:
            left, right = placement.x - half, placement.x + half
        expected_box = (left, placement.y - 9, right, placement.y + 3)
        bad += check(
            placement.box == expected_box,
            f"{placement.node_id} box {placement.box} does not match final placement {expected_box}",
        )
        emitted = (
            f'<text class="node-label" x="{placement.x}" y="{placement.y}" '
            f'text-anchor="{placement.anchor}">{placement.text}</text>'
        )
        bad += check(
            markup.count(emitted) == 1,
            f"{placement.node_id} final placement was not emitted exactly: {emitted}",
        )
    return bad


def main() -> int:
    bad = 0

    g = edge_graph()
    placements = render.label_placements(g)
    kept = {placement.node_id: placement for placement in placements}

    bad += check(len(kept) == 5, f"expected all five labels kept, got {sorted(kept)}")
    bad += check(kept["left"].anchor == "start", "left-edge label is not start-anchored")
    bad += check(kept["right"].anchor == "end", "right-edge label is not end-anchored")

    for node_id, placement in kept.items():
        left, top, right, bottom = placement.box
        bad += check(left >= 0, f"{node_id} label left {left} is left of the viewBox (x=0)")
        bad += check(
            right <= g["width"],
            f"{node_id} label right {right} exceeds viewBox width {g['width']}",
        )
        bad += check(top >= 0, f"{node_id} label top {top} is above the viewBox (y=0)")
        bad += check(
            bottom <= g["height"],
            f"{node_id} label bottom {bottom} exceeds viewBox height {g['height']}",
        )

    # The clamp must not have papered over the fallback logic: boxes still
    # must not overlap each other.
    values = [placement.box for placement in kept.values()]
    for i, a in enumerate(values):
        for b in values[i + 1:]:
            bad += check(not overlaps(a, b), f"clamped label boxes overlap: {a} vs {b}")
    bad += check_contract(g, placements)

    cg = edge_collision_graph()
    collision_placements = render.label_placements(cg)
    collision_kept = {placement.node_id: placement for placement in collision_placements}
    bad += check(
        len(collision_kept) == 2,
        f"expected both edge-collision labels kept, got {sorted(collision_kept)}",
    )
    if len(collision_kept) == 2:
        left = collision_kept["left"]
        right = collision_kept["right"]
        bad += check(left.anchor == "start", "collision fixture left label is not start-anchored")
        bad += check(right.anchor == "end", "collision fixture right label is not end-anchored")
        bad += check(
            not overlaps(left.box, right.box),
            f"final edge-anchored boxes overlap: {left.box} vs {right.box}",
        )
    bad += check_contract(cg, collision_placements)

    fg = fractional_graph()
    fractional_placements = render.label_placements(fg)
    fractional = next(p for p in fractional_placements if p.node_id == "fractional")
    bad += check(
        fractional.y == 39.04 and fractional.box[1] == 30.04,
        f"fractional placement lost precision: y={fractional.y}, box={fractional.box}",
    )
    bad += check_contract(fg, fractional_placements)

    dg = degenerate_graph()
    dplacements = render.label_placements(dg)
    for placement in dplacements:
        left, top, right, bottom = placement.box
        bad += check(top <= bottom, f"{placement.node_id} degenerate box inverted: {placement.box}")
        bad += check(top >= 0, f"{placement.node_id} degenerate box top {top} is negative")

    print("test_graph_label_bounds:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
