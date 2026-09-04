#!/usr/bin/env python3
"""Weighting and layout. The weighting encodes a claim about what collaboration
means, so each part of the claim gets a test that would break if the claim
stopped holding."""
import sqlite3
import sys

import db
import graph


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def _corpus(rows):
    conn = db.connect(":memory:")
    conn.execute(
        "INSERT INTO raw_payload(sha256,url,fetched_at,path) VALUES('s','u','t','p')"
    )
    for wid, year, members in rows:
        conn.execute(
            "INSERT INTO work(id,title,year,abstract_reason,raw_sha) VALUES(?,?,?,'x','s')",
            (wid, wid, year),
        )
        for i, (aid, pos) in enumerate(members):
            conn.execute("INSERT OR IGNORE INTO author(id,display_name) VALUES(?,?)", (aid, aid))
            conn.execute(
                "INSERT INTO authorship(work_id,author_id,ordinal,author_position)"
                " VALUES(?,?,?,?)",
                (wid, aid, i, pos),
            )
    return conn


def weight_of(conn, a, b):
    x, y = db.pair(a, b)
    row = conn.execute(
        "SELECT weight FROM coauthorship WHERE a_id=? AND b_id=?", (x, y)
    ).fetchone()
    return row["weight"] if row else None


def main() -> int:
    bad = 0

    # Team size: a two-author paper is stronger evidence of collaboration than
    # a 900-author one, and the factor must be strictly decreasing.
    factors = [graph.team_factor(n) for n in (2, 5, 25, 100, 900)]
    bad += check(all(a > b for a, b in zip(factors, factors[1:])), f"team_factor not decreasing: {factors}")
    bad += check(graph.team_factor(1) == 1.0, "solo team factor")

    # Recency: a ten-year half-life, exactly.
    bad += check(abs(graph.recency_factor(2026, 2026) - 1.0) < 1e-9, "this year should be 1.0")
    bad += check(abs(graph.recency_factor(2016, 2026) - 0.5) < 1e-9, "ten years should halve")
    bad += check(graph.recency_factor(None, 2026) == 0.5, "unknown year fallback")

    # Position: both lead > one lead > neither.
    bad += check(
        graph.position_factor("first", "last")
        > graph.position_factor("first", "middle")
        > graph.position_factor("middle", "middle"),
        "position factors not ordered",
    )

    # The end-to-end claim: two lead authors on a small recent paper must
    # outweigh two middle authors on a large old one, even though both pairs
    # share exactly one work.
    conn = _corpus(
        [
            ("W1", 2025, [("A", "first"), ("B", "last")]),
            ("W2", 1995, [("C", "first")] + [(f"M{i}", "middle") for i in range(40)] + [("D", "last")]),
        ]
    )
    graph.build_coauthorship(conn, 2026)
    small = weight_of(conn, "A", "B")
    large = weight_of(conn, "M0", "M1")
    bad += check(small > large * 10, f"small-team lead pair {small} not >> big-team middles {large}")

    # Shared-work count is still recorded truthfully even though it is not the ranking.
    row = conn.execute("SELECT works FROM coauthorship WHERE a_id='A' AND b_id='B'").fetchone()
    bad += check(row["works"] == 1, "works count wrong")

    # The a_id < b_id CHECK is what stops a pair being stored twice. Prove the
    # constraint is live rather than trusting that the writer happens to order.
    try:
        conn.execute(
            "INSERT INTO coauthorship(a_id,b_id,works,weight) VALUES('Z','A',1,1.0)"
        )
        bad += check(False, "unordered pair was accepted; the CHECK is not enforced")
    except sqlite3.IntegrityError:
        pass

    # A one-author work contributes no edges at all.
    conn2 = _corpus([("W9", 2020, [("solo", "first")])])
    bad += check(graph.build_coauthorship(conn2, 2026) == 0, "solo work made an edge")

    # Layout: same input, same output -- this is what makes an SVG diff in a
    # pull request a real change rather than simulation noise.
    nodes = ["n%d" % i for i in range(12)]
    edges = [(nodes[i], nodes[i + 1], 1.0) for i in range(11)]
    a = graph.layout(nodes, edges)
    b = graph.layout(list(reversed(nodes)), list(reversed(edges)))
    bad += check(a == b, "layout depends on input order")
    bad += check(graph.layout([], []) == {}, "empty layout")
    bad += check(len(graph.layout(["only"], [])) == 1, "single-node layout")

    # And it must stay inside the viewBox, or nodes vanish off the SVG edge.
    for x, y in a.values():
        bad += check(0 <= x <= 1000 and 0 <= y <= 700, f"node outside canvas: {x},{y}")

    print("test_graph:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
