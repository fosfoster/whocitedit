#!/usr/bin/env python3
"""Corpus database -> the committed JSON the reader is built from. No network.

This is the boundary that makes the board buildable by agents. Everything
upstream of it needs the network, a credit budget and a residential IP;
everything downstream is a static site build over files in the repo. A builder
and CI only ever see what this writes.

Two shapes matter.

SHARDED, NOT PER-ENTITY. One file per work would be 3,000 files and one per
author more than twice that, which is a slow `next build` and a git tree nothing
can review. Entities are bucketed by two characters of their id, so a corpus of
this size is a couple of hundred files and a shard diff shows what changed.

LAYOUT IS BAKED IN. Every graph ships with coordinates already solved by
`graph.layout`. The reader draws SVG from them and never runs a simulation, so
the page is identical for every reader, needs no JavaScript to show the graph,
and can be crawled.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import graph
import identity
import quality
from db import DB_PATH, connect, get_meta
from licensing import ABSTRACT_RENDERED

ROOT = Path(__file__).parent
OUT = ROOT / "web" / "data"

# TRAILING characters, not leading ones. OpenAlex ids are a letter plus a
# monotonic number, so every author id currently begins `A5` and every work id
# `W2`/`W3` -- sharding on the front put 5,332 of 6,906 authors in one file and
# left the rest nearly empty. The last two digits are uniform.
SHARD_LEN = 2

# A citation neighbourhood past this many nodes is a hairball: it takes longer
# to lay out, renders as a smudge, and tells the reader less than the top slice
# does. The page says how many were shown out of how many exist.
MAX_WORK_GRAPH_NODES = 36
MAX_AUTHOR_GRAPH_NODES = 24

# THE GRAPH BUDGET SCALES WITH THE EVIDENCE BEHIND IT. Two thirds of the rows in
# a corpus this shape hold exactly one work, and a single 300-author paper hands
# every one of those authors 299 "collaborators" it knows nothing else about.
# Drawing 24 of them is a picture of that paper's author list wearing a graph's
# clothes. An author with one work gets a small neighbourhood; one with a real
# publication record in the corpus gets the full one.
SINGLE_WORK_GRAPH_NODES = 8

# Second-order edges are what turn a star into a picture of a group, and they
# are also where the export blows up: 24 mutually-connected collaborators is 276
# edges on one page, and a corpus with mega-author papers in it hits that
# ceiling on thousands of pages at once. The first cut of this export was 83 MB
# for that reason alone. Keeping the strongest 120 draws the same picture.
MAX_INNER_EDGES = 80

# Titles inside a graph node are labels, not content -- the full title is in the
# work payload the node links to. Repeating a 300-character title 36 times per
# page across 3,000 pages is several megabytes of duplication.
MAX_NODE_LABEL = 90



def _display(path: Path) -> str:
    """Repo-relative when it can be, absolute otherwise.

    `Path.relative_to` raises rather than falling back, so a progress line
    crashed the run whenever the output directory was pointed somewhere else --
    which is exactly what the pipeline test does.
    """
    try:
        return str(path.relative_to(Path(__file__).parent))
    except ValueError:
        return str(path)

def shard(entity_id: str) -> str:
    return entity_id[-SHARD_LEN:].lower() or "00"


def _write(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    path.write_text(body)
    return len(body)


def _provenance(conn, sha: str | None) -> str | None:
    """Entities carry the payload HASH; the URL lives once in `payloads.json`.

    A harvested author page comes from a 50-id OR-filter URL roughly a kilobyte
    long. Embedding it in each of 6,906 author payloads spent 7 MB restating
    the same 150 URLs.
    """
    return sha or None


def work_payload(conn, row, neighbourhood) -> dict:
    wid = row["id"]
    authors = [
        {
            "id": r["author_id"],
            "name": r["display_name"],
            "position": r["author_position"],
            "confidence": r["confidence"],
        }
        for r in conn.execute(
            "SELECT a.author_id, a.author_position, au.display_name, au.confidence "
            "FROM authorship a JOIN author au ON au.id = a.author_id "
            "WHERE a.work_id = ? ORDER BY a.ordinal",
            (wid,),
        )
    ]
    topics = [
        {"id": r["id"], "name": r["display_name"], "field": r["field"]}
        for r in conn.execute(
            "SELECT t.id, t.display_name, t.field FROM work_topic wt "
            "JOIN topic t ON t.id = wt.topic_id WHERE wt.work_id = ? "
            "ORDER BY wt.score DESC",
            (wid,),
        )
    ]
    return {
        "id": wid,
        "title": row["title"],
        "year": row["year"],
        "date": row["publication_date"],
        "type": row["type"],
        "doi": row["doi"],
        "source": {"id": row["source_id"], "name": row["source_name"]},
        "oa": {
            "is_oa": bool(row["is_oa"]),
            "status": row["oa_status"],
            "url": row["oa_url"],
            "license": row["oa_license"],
        },
        # Belt and braces with the schema CHECK: the column cannot hold text
        # under a withholding reason, and this refuses to emit it if it ever does.
        "abstract": {
            "text": row["abstract"] if row["abstract_reason"] == ABSTRACT_RENDERED else None,
            "reason": row["abstract_reason"],
        },
        "cited_by_count": row["cited_by_count"],
        "referenced_count": row["referenced_count"],
        "quality": {
            "band": row["quality"] or quality.COMPLETE,
            "sentence": quality.band_sentence(row["quality"] or quality.COMPLETE),
            "evidence": quality.decode_evidence(row["quality_evidence"]),
        },
        "authors": authors,
        "topics": topics,
        "graph": neighbourhood,
        "raw": _provenance(conn, row["raw_sha"]),
        "openalex_url": f"https://openalex.org/{wid}",
    }


def work_graph(conn, wid: str, titles: dict[str, dict]) -> dict:
    hood = graph.citation_neighborhood(conn, wid, limit=MAX_WORK_GRAPH_NODES)
    refs, citers = hood["references"], hood["cited_by"]
    total = len(refs) + len(citers)
    budget = MAX_WORK_GRAPH_NODES
    # Split the budget between the two directions rather than letting a heavily
    # cited work crowd out every reference it stands on.
    keep_refs = refs[: max(budget // 2, budget - len(citers))]
    keep_citers = citers[: budget - len(keep_refs)]

    node_ids = [wid] + keep_refs + keep_citers
    edges = [(c, wid, 1.0) for c in keep_citers] + [(wid, r, 1.0) for r in keep_refs]
    coords = graph.layout(node_ids, edges, seed=7, width=1000, height=640)

    def node(nid: str, kind: str) -> dict:
        meta = titles.get(nid, {})
        x, y = coords.get(nid, (500.0, 320.0))
        label = meta.get("title", nid)
        return {
            "id": nid,
            "label": label if len(label) <= MAX_NODE_LABEL else label[: MAX_NODE_LABEL - 1] + "\u2026",
            "year": meta.get("year"),
            "cited": meta.get("cited_by_count", 0),
            "kind": kind,
            "x": x,
            "y": y,
        }

    return {
        "width": 1000,
        "height": 640,
        "nodes": [node(wid, "focus")]
        + [node(n, "reference") for n in keep_refs]
        + [node(n, "citer") for n in keep_citers],
        "edges": [{"s": s, "t": t} for s, t, _ in edges],
        "shown": len(node_ids) - 1,
        "available": total,
    }


def load_coauthorship(conn) -> tuple[dict[str, list], dict[tuple[str, str], float]]:
    """Adjacency, built once.

    The first cut asked SQL for one author's neighbours and then for the edges
    among them, per author. That is 14,000 queries over the same small table and
    it was 97 of the export's 98 seconds.
    """
    adj: dict[str, list] = {}
    weights: dict[tuple[str, str], float] = {}
    for r in conn.execute(
        "SELECT a_id, b_id, works, weight, first_year, last_year FROM coauthorship"
    ):
        rec_a = (r["b_id"], r["works"], r["weight"], r["first_year"], r["last_year"])
        rec_b = (r["a_id"], r["works"], r["weight"], r["first_year"], r["last_year"])
        adj.setdefault(r["a_id"], []).append(rec_a)
        adj.setdefault(r["b_id"], []).append(rec_b)
        weights[(r["a_id"], r["b_id"])] = r["weight"]
    for v in adj.values():
        v.sort(key=lambda t: -t[2])
    return adj, weights


def author_graph(aid: str, names: dict[str, str], bands: dict[str, str], adj, weights,
                 works_in_corpus: int = 1) -> dict:
    rows = adj.get(aid, [])
    budget = MAX_AUTHOR_GRAPH_NODES if works_in_corpus > 1 else SINGLE_WORK_GRAPH_NODES
    kept = rows[:budget]
    others = [r[0] for r in kept]
    node_ids = [aid] + others
    edges = [(aid, r[0], r[2]) for r in kept]

    # Second-order edges: collaborations *between* this author's collaborators.
    # This is the part a list of co-author names cannot show at all.
    inner: list[tuple[str, str, float]] = []
    for i in range(len(others)):
        for j in range(i + 1, len(others)):
            a, b = (others[i], others[j]) if others[i] < others[j] else (others[j], others[i])
            w = weights.get((a, b))
            if w is not None:
                inner.append((a, b, w))
    inner.sort(key=lambda t: -t[2])
    edges.extend(inner[:MAX_INNER_EDGES])

    coords = graph.layout(node_ids, edges, seed=11, width=900, height=620)
    weight_by = {r[0]: r for r in kept}

    def node(nid: str, kind: str) -> dict:
        x, y = coords.get(nid, (450.0, 310.0))
        r = weight_by.get(nid)
        return {
            "id": nid,
            "label": names.get(nid, nid),
            "kind": kind,
            "confidence": bands.get(nid),
            "works": r[1] if r else None,
            "weight": round(r[2], 2) if r else None,
            "first_year": r[3] if r else None,
            "last_year": r[4] if r else None,
            "x": x,
            "y": y,
        }

    return {
        "width": 900,
        "height": 620,
        "nodes": [node(aid, "focus")] + [node(n, "coauthor") for n in others],
        "edges": [
            {"s": s, "t": t, "w": round(w, 3), "inner": s != aid and t != aid}
            for s, t, w in edges
        ],
        "shown": len(others),
        "available": len(rows),
    }


def main() -> int:
    if not DB_PATH.exists():
        print("no corpus database: run `python3 derive.py` first", file=sys.stderr)
        return 1
    conn = connect(DB_PATH)
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    titles = {
        r["id"]: {"title": r["title"], "year": r["year"], "cited_by_count": r["cited_by_count"]}
        for r in conn.execute("SELECT id, title, year, cited_by_count FROM work")
    }
    names = {r["id"]: r["display_name"] for r in conn.execute("SELECT id, display_name FROM author")}
    bands = {r["id"]: r["confidence"] for r in conn.execute("SELECT id, confidence FROM author")}

    adj, weights = load_coauthorship(conn)

    in_cites = {
        r["cited_id"]: r["n"]
        for r in conn.execute("SELECT cited_id, COUNT(*) n FROM citation GROUP BY cited_id")
    }

    # -- works -----------------------------------------------------------
    work_shards: dict[str, dict] = {}
    work_index = []
    for row in conn.execute("SELECT * FROM work ORDER BY cited_by_count DESC"):
        wid = row["id"]
        payload = work_payload(conn, row, work_graph(conn, wid, titles))
        payload["in_corpus_cited_by"] = in_cites.get(wid, 0)
        work_shards.setdefault(shard(wid), {})[wid] = payload
        work_index.append(
            {
                "id": wid,
                "title": row["title"],
                "year": row["year"],
                "cited": row["cited_by_count"],
                "in_corpus_cited": in_cites.get(wid, 0),
                "authors": [a["name"] for a in payload["authors"][:4]],
                "n_authors": len(payload["authors"]),
                "oa": bool(row["is_oa"]),
                "quality": row["quality"] or quality.COMPLETE,
            }
        )
    total_bytes = 0
    for name, blob in work_shards.items():
        total_bytes += _write(OUT / "works" / f"{name}.json", blob)
    total_bytes += _write(OUT / "works-index.json", work_index)

    # -- authors ---------------------------------------------------------
    author_shards: dict[str, dict] = {}
    author_index = []
    for row in conn.execute(
        "SELECT au.*, COUNT(a.work_id) AS n_works FROM author au "
        "JOIN authorship a ON a.author_id = au.id GROUP BY au.id "
        "ORDER BY n_works DESC, au.cited_by_count DESC"
    ):
        aid = row["id"]
        works = [
            {
                "id": r["work_id"],
                "title": titles[r["work_id"]]["title"],
                "year": titles[r["work_id"]]["year"],
                "cited": titles[r["work_id"]]["cited_by_count"],
                "position": r["author_position"],
            }
            for r in conn.execute(
                "SELECT work_id, author_position FROM authorship WHERE author_id = ?", (aid,)
            )
        ]
        works.sort(key=lambda w: -(w["cited"] or 0))
        insts = [
            {"id": r["id"], "name": r["display_name"], "ror": r["ror"],
             "first_year": r["first_year"], "last_year": r["last_year"]}
            for r in conn.execute(
                "SELECT i.id, i.display_name, i.ror, MIN(af.year) first_year, MAX(af.year) last_year "
                "FROM affiliation af JOIN institution i ON i.id = af.institution_id "
                "WHERE af.author_id = ? GROUP BY i.id ORDER BY last_year DESC",
                (aid,),
            )
        ]
        band = row["confidence"] or identity.LOW
        payload = {
            "id": aid,
            "name": row["display_name"],
            "orcid": row["orcid"],
            "works_count": row["works_count"],
            "cited_by_count": row["cited_by_count"],
            "confidence": {
                "band": band,
                "sentence": identity.band_sentence(band),
                "evidence": identity.decode_evidence(row["confidence_evidence"]),
            },
            "in_corpus": {
                "works": len(works),
                "citations": sum(w["cited"] or 0 for w in works),
                "hindex": identity.hindex([w["cited"] or 0 for w in works]),
            },
            "works": works,
            "institutions": insts,
            "graph": author_graph(aid, names, bands, adj, weights, len(works)),
            "raw": _provenance(conn, row["raw_sha"]),
            "openalex_url": f"https://openalex.org/{aid}",
        }
        author_shards.setdefault(shard(aid), {})[aid] = payload
        author_index.append(
            {
                "id": aid,
                "name": row["display_name"],
                "band": band,
                "works": len(works),
                "cited": row["cited_by_count"],
                "coauthors": payload["graph"]["available"],
                "orcid": bool(row["orcid"]),
            }
        )
    for name, blob in author_shards.items():
        total_bytes += _write(OUT / "authors" / f"{name}.json", blob)
    total_bytes += _write(OUT / "authors-index.json", author_index)

    # -- provenance ------------------------------------------------------
    # Every entity names one of these by hash. This is the file that makes
    # "which bytes did this number come from" answerable on the page itself.
    total_bytes += _write(
        OUT / "payloads.json",
        {
            r["sha256"]: {"url": r["url"], "fetched_at": r["fetched_at"]}
            for r in conn.execute("SELECT sha256, url, fetched_at FROM raw_payload")
        },
    )

    # -- corpus ----------------------------------------------------------
    definition = json.loads((ROOT / "corpus.json").read_text())
    bands_count = {b: sum(1 for a in author_index if a["band"] == b) for b in ("high", "medium", "low")}
    withheld = conn.execute(
        "SELECT abstract_reason, COUNT(*) c FROM work GROUP BY abstract_reason"
    ).fetchall()
    _write(
        OUT / "corpus.json",
        {
            "definition": definition,
            "derived_at": get_meta(conn, "derived_at"),
            "counts": {
                "works": len(work_index),
                "authors": len(author_index),
                "citations": conn.execute("SELECT COUNT(*) c FROM citation").fetchone()["c"],
                "coauthor_edges": conn.execute("SELECT COUNT(*) c FROM coauthorship").fetchone()["c"],
                "institutions": conn.execute("SELECT COUNT(*) c FROM institution").fetchone()["c"],
            },
            "identity": bands_count,
            "quality": {
                b: conn.execute(
                    "SELECT COUNT(*) c FROM work WHERE quality = ?", (b,)
                ).fetchone()["c"]
                for b in (quality.COMPLETE, quality.PARTIAL, quality.SUSPECT)
            },
            "quality_notes": quality.NOTE_TEMPLATES,
            "quality_bands": quality.BAND_SENTENCES,
            # Shipped rather than duplicated in the reader: identity.py is the
            # single definition of how a signal is described, and the reader
            # formats these instead of keeping its own TypeScript copy.
            "identity_notes": identity.NOTE_TEMPLATES,
            "identity_bands": identity.BAND_SENTENCES,
            "abstracts": {r["abstract_reason"]: r["c"] for r in withheld},
            "sources": [
                {
                    "name": "OpenAlex",
                    "url": "https://openalex.org",
                    "license": "CC0",
                    "role": "works, authors, institutions, topics and citation edges",
                }
            ],
        },
    )
    print(f"== wrote {len(work_index)} works and {len(author_index)} authors "
          f"({total_bytes / 1e6:.1f} MB) to {_display(OUT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
