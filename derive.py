#!/usr/bin/env python3
"""Turn stored raw payloads into the corpus database. No network.

Replayable by construction: this reads `harvest/raw/` and nothing else, so a
schema change or a scoring change costs zero API credits and produces a database
that still traces every row to the bytes it came from.

The one rule worth stating up front: A CITATION EDGE IS ONLY STORED WHEN BOTH
ENDS ARE IN THE CORPUS. OpenAlex hands us `referenced_works` for every work,
most of which point outside a 3,000-work set. Storing those would give the site
dangling nodes it can render nothing for, and would make `cited_by_count` inside
the graph disagree with the number shown beside it. Works keep their global
`cited_by_count` as published; the graph is explicitly the in-corpus subgraph and
the pages say so.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import graph
import identity
import quality
from db import DB_PATH, connect, set_meta
from licensing import abstract_decision
from openalex import short_id

ROOT = Path(__file__).parent
RAW = ROOT / "harvest" / "raw"
MANIFEST = ROOT / "harvest" / "manifest.jsonl"


def _manifest_index() -> dict[str, dict]:
    """sha256 -> the newest manifest record for it."""
    index: dict[str, dict] = {}
    if not MANIFEST.exists():
        return index
    for line in MANIFEST.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        index[rec["sha256"]] = rec
    return index


def _payloads():
    manifest = _manifest_index()
    for path in sorted(RAW.rglob("*.json")):
        sha = path.stem
        rec = manifest.get(sha) or {
            "url": "unknown",
            "fetched_at": "unknown",
            "path": str(path.relative_to(ROOT)),
            "sha256": sha,
        }
        yield rec, json.loads(path.read_text())


def _is_work(obj: dict) -> bool:
    return "authorships" in obj or "referenced_works" in obj


def _is_author(obj: dict) -> bool:
    return "display_name" in obj and "works_count" in obj and "authorships" not in obj


def load(conn) -> dict:
    stats = {"payloads": 0, "works": 0, "authors": 0, "authorships": 0}
    references: dict[str, list[str]] = {}

    for rec, payload in _payloads():
        stats["payloads"] += 1
        conn.execute(
            "INSERT OR REPLACE INTO raw_payload(sha256, url, fetched_at, path) "
            "VALUES(?,?,?,?)",
            (rec["sha256"], rec["url"], rec["fetched_at"], rec["path"]),
        )
        for obj in payload.get("results") or []:
            if _is_work(obj):
                references[_insert_work(conn, obj, rec["sha256"])] = [
                    short_id(r) for r in (obj.get("referenced_works") or [])
                ]
                stats["works"] += 1
            elif _is_author(obj):
                _insert_author(conn, obj, rec["sha256"])
                stats["authors"] += 1

    stats["authorships"] = conn.execute("SELECT COUNT(*) c FROM authorship").fetchone()["c"]
    stats["citations"] = _insert_citations(conn, references)
    return stats


def _title(w: dict) -> str:
    """Never the bare word "Untitled".

    Seven works in the first harvest carry no title at all, and rendering them as
    a row that says "Untitled" tells a reader nothing and looks like our bug
    rather than the source's gap. Fall back to what the record does have, and
    say plainly that the title is missing upstream.
    """
    title = (w.get("title") or "").strip()
    if title:
        return title
    src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name")
    hint = src or (w.get("doi") or "").replace("https://doi.org/", "") or short_id(w["id"])
    return f"[No title in the source record — {hint}]"


def _insert_work(conn, w: dict, raw_sha: str) -> str:
    wid = short_id(w["id"])
    abstract, reason, license_id = abstract_decision(w)
    best = w.get("best_oa_location") or {}
    src = (w.get("primary_location") or {}).get("source") or {}
    conn.execute(
        """INSERT OR REPLACE INTO work(
             id, doi, title, year, publication_date, type, source_id, source_name,
             is_oa, oa_status, oa_url, oa_license, abstract, abstract_reason,
             cited_by_count, referenced_count, is_seed, raw_sha)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
        (
            wid,
            w.get("doi"),
            _title(w),
            w.get("publication_year"),
            w.get("publication_date"),
            w.get("type"),
            short_id(src.get("id")),
            src.get("display_name"),
            1 if (w.get("open_access") or {}).get("is_oa") else 0,
            (w.get("open_access") or {}).get("oa_status"),
            best.get("landing_page_url") or (w.get("open_access") or {}).get("oa_url"),
            license_id,
            abstract,
            reason,
            w.get("cited_by_count") or 0,
            len(w.get("referenced_works") or []),
            raw_sha,
        ),
    )

    for topic in (w.get("topics") or [])[:3]:
        tid = short_id(topic.get("id"))
        if not tid:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO topic(id, display_name, field, domain) VALUES(?,?,?,?)",
            (
                tid,
                topic.get("display_name") or tid,
                (topic.get("field") or {}).get("display_name"),
                (topic.get("domain") or {}).get("display_name"),
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO work_topic(work_id, topic_id, score) VALUES(?,?,?)",
            (wid, tid, topic.get("score")),
        )

    for ordinal, a in enumerate(w.get("authorships") or []):
        aid = short_id((a.get("author") or {}).get("id"))
        if not aid:
            continue
        # A stub row so the foreign key holds even when the author payload has
        # not been harvested yet. `_insert_author` fills it in later; a corpus
        # with a missing author fetch degrades to a name, not to a crash.
        conn.execute(
            "INSERT OR IGNORE INTO author(id, display_name) VALUES(?,?)",
            (aid, (a.get("author") or {}).get("display_name") or aid),
        )
        conn.execute(
            "INSERT OR REPLACE INTO authorship("
            "  work_id, author_id, ordinal, author_position, raw_name, is_corresponding)"
            " VALUES(?,?,?,?,?,?)",
            (
                wid,
                aid,
                ordinal,
                a.get("author_position"),
                a.get("raw_author_name"),
                1 if a.get("is_corresponding") else 0,
            ),
        )
        for inst in a.get("institutions") or []:
            iid = short_id(inst.get("id"))
            if not iid:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO institution(id, display_name, ror, country_code, type)"
                " VALUES(?,?,?,?,?)",
                (
                    iid,
                    inst.get("display_name") or iid,
                    inst.get("ror"),
                    inst.get("country_code"),
                    inst.get("type"),
                ),
            )
            conn.execute(
                "INSERT OR REPLACE INTO affiliation(author_id, institution_id, work_id, year)"
                " VALUES(?,?,?,?)",
                (aid, iid, wid, w.get("publication_year")),
            )
    return wid


def _insert_author(conn, a: dict, raw_sha: str) -> None:
    aid = short_id(a["id"])
    insts = a.get("last_known_institutions") or []
    for inst in insts:
        iid = short_id(inst.get("id"))
        if iid:
            conn.execute(
                "INSERT OR REPLACE INTO institution(id, display_name, ror, country_code, type)"
                " VALUES(?,?,?,?,?)",
                (iid, inst.get("display_name") or iid, inst.get("ror"),
                 inst.get("country_code"), inst.get("type")),
            )
    conn.execute(
        "INSERT INTO author(id, display_name, orcid, works_count, cited_by_count, raw_sha)"
        " VALUES(?,?,?,?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name,"
        "   orcid=excluded.orcid, works_count=excluded.works_count,"
        "   cited_by_count=excluded.cited_by_count, raw_sha=excluded.raw_sha",
        (
            aid,
            a.get("display_name") or aid,
            (a.get("orcid") or "").rsplit("/", 1)[-1] or None,
            a.get("works_count") or 0,
            a.get("cited_by_count") or 0,
            raw_sha,
        ),
    )


def _insert_citations(conn, references: dict[str, list[str]]) -> int:
    in_corpus = {r["id"] for r in conn.execute("SELECT id FROM work")}
    rows = [
        (citing, cited)
        for citing, cited_ids in references.items()
        for cited in cited_ids
        if cited in in_corpus and cited != citing
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO citation(citing_id, cited_id, sources) VALUES(?,?,'[\"openalex\"]')",
        rows,
    )
    return conn.execute("SELECT COUNT(*) c FROM citation").fetchone()["c"]


def score_quality(conn) -> dict[str, int]:
    """Flag work records that contradict themselves. Nothing is deleted."""
    bands = {quality.COMPLETE: 0, quality.PARTIAL: 0, quality.SUSPECT: 0}
    for row in conn.execute(
        "SELECT w.id, w.title, w.doi, w.year, w.referenced_count, w.cited_by_count,"
        "       (SELECT COUNT(*) FROM authorship a WHERE a.work_id = w.id) AS n_authors"
        "  FROM work w"
    ):
        band, evidence = quality.assess(
            title=row["title"],
            doi=row["doi"],
            year=row["year"],
            n_authors=row["n_authors"],
            referenced_count=row["referenced_count"],
            cited_by_count=row["cited_by_count"],
        )
        bands[band] += 1
        conn.execute(
            "UPDATE work SET quality = ?, quality_evidence = ? WHERE id = ?",
            (band, quality.encode_evidence(evidence), row["id"]),
        )
    return bands


def score_identities(conn) -> dict[str, int]:
    bands = {identity.HIGH: 0, identity.MEDIUM: 0, identity.LOW: 0}
    for row in conn.execute("SELECT id, orcid FROM author"):
        aid = row["id"]
        names = [
            r["raw_name"]
            for r in conn.execute(
                "SELECT raw_name FROM authorship WHERE author_id = ?", (aid,)
            )
            if r["raw_name"]
        ]
        insts = [
            (r["institution_id"], r["year"])
            for r in conn.execute(
                "SELECT institution_id, year FROM affiliation WHERE author_id = ?", (aid,)
            )
        ]
        fields = [
            r["field"]
            for r in conn.execute(
                "SELECT t.field FROM authorship a "
                "JOIN work_topic wt ON wt.work_id = a.work_id "
                "JOIN topic t ON t.id = wt.topic_id WHERE a.author_id = ?",
                (aid,),
            )
            if r["field"]
        ]
        n = conn.execute(
            "SELECT COUNT(*) c FROM authorship WHERE author_id = ?", (aid,)
        ).fetchone()["c"]
        band, evidence = identity.assess(
            orcid=row["orcid"],
            raw_names=names,
            institution_years=insts,
            topic_fields=fields,
            works_in_corpus=n,
        )
        bands[band] += 1
        conn.execute(
            "UPDATE author SET confidence = ?, confidence_evidence = ? WHERE id = ?",
            (band, identity.encode_evidence(evidence), aid),
        )
    return bands


def main() -> int:
    if not RAW.exists() or not any(RAW.rglob("*.json")):
        print("no raw payloads: run `python3 harvest.py` first", file=sys.stderr)
        return 1
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = connect(DB_PATH)
    now_year = datetime.now(timezone.utc).year

    print("== loading raw payloads")
    stats = load(conn)
    print(f"   {stats['payloads']} payloads -> {stats['works']} works, "
          f"{stats['authors']} author records, {stats['authorships']} authorships, "
          f"{stats['citations']} in-corpus citations")

    print("== co-authorship")
    edges = graph.build_coauthorship(conn, now_year)
    print(f"   {edges} weighted edges")

    print("== work record quality")
    wbands = score_quality(conn)
    print(f"   complete={wbands['complete']} partial={wbands['partial']} suspect={wbands['suspect']}")

    print("== identity confidence")
    bands = score_identities(conn)
    print(f"   high={bands['high']} medium={bands['medium']} low={bands['low']}")

    set_meta(conn, "derived_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    set_meta(conn, "stats", {**stats, "coauthor_edges": edges, "identity": bands, "quality": wbands})
    conn.commit()
    print(f"== wrote {DB_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
