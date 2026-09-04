#!/usr/bin/env python3
"""Edges and the layouts that get drawn.

Two decisions here are the product rather than the plumbing.

CO-AUTHORSHIP IS WEIGHTED, NOT COUNTED. Every tool in this category renders
co-authorship as "number of shared papers", which makes two middle authors on a
900-author collaboration paper look like collaborators and makes a two-person
paper look like a footnote. Weight here multiplies three things: how small the
author list was, whether both people held a lead position on it, and how
recently it happened. That is a claim about what collaboration means and the
methodology page states it in those terms so a reader can disagree with it.

LAYOUT IS COMPUTED HERE, NOT IN THE BROWSER. Every competitor ships a graph as
JSON and runs a force simulation on the reader's machine behind a login. Solving
it once at build time is what makes these pages static, fast, crawlable and
identical for every reader -- and it is why the layout has to be deterministic:
a seeded run means the same corpus produces the same SVG, so a diff in a pull
request is a real change rather than simulation noise.
"""
from __future__ import annotations

import json
import math
import random
from collections import defaultdict

from db import pair

# Ten-year half-life. A paper written together last year is stronger evidence of
# a working relationship than one from 1998, and a graph that does not decay
# shows a researcher's whole career as though it were their current network.
RECENCY_HALF_LIFE_YEARS = 10.0

# Lead positions carry the collaboration. `first` and `last` are the two that
# mean something across most of science; everything else is `middle`.
LEAD_POSITIONS = frozenset({"first", "last"})

BOTH_LEAD = 1.0
ONE_LEAD = 0.6
NEITHER_LEAD = 0.3

# Above this, an author list is a collaboration roster rather than a team, and
# every pair inside it would otherwise be scored as though they had worked
# together. The edge is not dropped -- it is damped and the page says so.
LARGE_TEAM_THRESHOLD = 25


def team_factor(n_authors: int) -> float:
    """1.0 for a solo-ish paper, decaying with the size of the author list."""
    if n_authors <= 1:
        return 1.0
    return 1.0 / math.log2(n_authors + 1)


def recency_factor(year: int | None, now_year: int) -> float:
    if not year:
        return 0.5
    age = max(now_year - year, 0)
    return 0.5 ** (age / RECENCY_HALF_LIFE_YEARS)


def position_factor(pos_a: str | None, pos_b: str | None) -> float:
    leads = (pos_a in LEAD_POSITIONS) + (pos_b in LEAD_POSITIONS)
    return {2: BOTH_LEAD, 1: ONE_LEAD, 0: NEITHER_LEAD}[leads]


def build_coauthorship(conn, now_year: int) -> int:
    """Recompute the co-authorship table from `authorship`. Returns edge count."""
    conn.execute("DELETE FROM coauthorship")

    by_work: dict[str, list[tuple[str, str | None]]] = defaultdict(list)
    years: dict[str, int | None] = {}
    for row in conn.execute(
        "SELECT a.work_id, a.author_id, a.author_position, w.year "
        "FROM authorship a JOIN work w ON w.id = a.work_id"
    ):
        by_work[row["work_id"]].append((row["author_id"], row["author_position"]))
        years[row["work_id"]] = row["year"]

    acc: dict[tuple[str, str], dict] = {}
    for work_id, members in by_work.items():
        n = len(members)
        if n < 2:
            continue
        year = years.get(work_id)
        tf = team_factor(n)
        rf = recency_factor(year, now_year)
        for i in range(n):
            for j in range(i + 1, n):
                a_id, a_pos = members[i]
                b_id, b_pos = members[j]
                if a_id == b_id:
                    continue
                key = pair(a_id, b_id)
                slot = acc.setdefault(
                    key, {"works": 0, "first": year, "last": year, "weight": 0.0}
                )
                slot["works"] += 1
                slot["weight"] += tf * rf * position_factor(a_pos, b_pos)
                if year:
                    slot["first"] = min(slot["first"] or year, year)
                    slot["last"] = max(slot["last"] or year, year)

    conn.executemany(
        "INSERT INTO coauthorship(a_id, b_id, works, first_year, last_year, weight) "
        "VALUES(?,?,?,?,?,?)",
        [
            (a, b, v["works"], v["first"], v["last"], round(v["weight"], 6))
            for (a, b), v in acc.items()
        ],
    )
    return len(acc)


def citation_neighborhood(conn, work_id: str, limit: int = 40) -> dict:
    """One hop out from a work, both directions, inside the corpus.

    Ranked by in-corpus citation count rather than by global count: the reader is
    being shown this corpus's structure, and a globally famous work with one link
    into the neighbourhood tells them less than a well-connected local one.
    """
    refs = [
        r["cited_id"]
        for r in conn.execute(
            "SELECT c.cited_id FROM citation c JOIN work w ON w.id = c.cited_id "
            "WHERE c.citing_id = ? ORDER BY w.cited_by_count DESC LIMIT ?",
            (work_id, limit),
        )
    ]
    citers = [
        r["citing_id"]
        for r in conn.execute(
            "SELECT c.citing_id FROM citation c JOIN work w ON w.id = c.citing_id "
            "WHERE c.cited_id = ? ORDER BY w.cited_by_count DESC LIMIT ?",
            (work_id, limit),
        )
    ]
    return {"references": refs, "cited_by": citers}


# -- layout --------------------------------------------------------------

def layout(
    nodes: list[str],
    edges: list[tuple[str, str, float]],
    *,
    seed: int = 1,
    iterations: int = 220,
    width: float = 1000.0,
    height: float = 700.0,
) -> dict[str, tuple[float, float]]:
    """Deterministic Fruchterman-Reingold. Same input, same SVG, every time.

    Seeded from the node ids rather than from wall-clock or insertion order, so
    adding an unrelated work elsewhere in the corpus does not reshuffle a graph
    that did not change.
    """
    if not nodes:
        return {}
    if len(nodes) == 1:
        return {nodes[0]: (width / 2, height / 2)}

    order = sorted(nodes)
    idx = {n: i for i, n in enumerate(order)}
    rng = random.Random(f"{seed}:{','.join(order)}")

    pos = []
    for i in range(len(order)):
        angle = 2 * math.pi * i / len(order)
        jitter = rng.uniform(0.85, 1.15)
        pos.append(
            [
                width / 2 + math.cos(angle) * width * 0.35 * jitter,
                height / 2 + math.sin(angle) * height * 0.35 * jitter,
            ]
        )

    area = width * height
    k = math.sqrt(area / len(order))
    temp = width / 10.0
    cooling = temp / (iterations + 1)

    adj = [[] for _ in order]
    for a, b, w in edges:
        if a in idx and b in idx and a != b:
            adj[idx[a]].append((idx[b], w))
            adj[idx[b]].append((idx[a], w))

    for _ in range(iterations):
        disp = [[0.0, 0.0] for _ in order]
        for i in range(len(order)):
            for j in range(i + 1, len(order)):
                dx = pos[i][0] - pos[j][0]
                dy = pos[i][1] - pos[j][1]
                dist = math.hypot(dx, dy) or 0.01
                force = (k * k) / dist
                ux, uy = dx / dist, dy / dist
                disp[i][0] += ux * force
                disp[i][1] += uy * force
                disp[j][0] -= ux * force
                disp[j][1] -= uy * force
        for i, neighbours in enumerate(adj):
            for j, w in neighbours:
                dx = pos[i][0] - pos[j][0]
                dy = pos[i][1] - pos[j][1]
                dist = math.hypot(dx, dy) or 0.01
                force = (dist * dist) / k * min(max(w, 0.15), 3.0)
                ux, uy = dx / dist, dy / dist
                disp[i][0] -= ux * force
                disp[i][1] -= uy * force
        for i in range(len(order)):
            d = math.hypot(*disp[i]) or 0.01
            step = min(d, temp)
            pos[i][0] = min(width, max(0.0, pos[i][0] + disp[i][0] / d * step))
            pos[i][1] = min(height, max(0.0, pos[i][1] + disp[i][1] / d * step))
        temp -= cooling

    return _fit({n: (pos[idx[n]][0], pos[idx[n]][1]) for n in order}, width, height)


def _fit(coords: dict[str, tuple[float, float]], width: float, height: float, pad: float = 40.0):
    xs = [p[0] for p in coords.values()]
    ys = [p[1] for p in coords.values()]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    sx = (width - 2 * pad) / (maxx - minx) if maxx > minx else 1.0
    sy = (height - 2 * pad) / (maxy - miny) if maxy > miny else 1.0
    s = min(sx, sy)
    return {
        n: (round(pad + (x - minx) * s, 1), round(pad + (y - miny) * s, 1))
        for n, (x, y) in coords.items()
    }


def encode_sources(sources: list[str]) -> str:
    return json.dumps(sorted(set(sources)))
