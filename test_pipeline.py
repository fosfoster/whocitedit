#!/usr/bin/env python3
"""End to end over a small synthetic corpus: database -> JSON -> HTML.

This is the test that guards the contract the whole board rests on -- that a
builder can work against `web/data/` with no network and no harvest. It also
carries the leak test: an abstract we are not licensed to publish must not
appear anywhere in the exported JSON or in the rendered HTML, which is a
property no unit test of `licensing.py` alone can establish.
"""
import json
import re
import sqlite3
import shutil
import sys
import tempfile
from pathlib import Path

import db
import derive
import export_json
import graph
import render

SECRET = "ThisAbstractIsNotLicensedForRedistribution"
HOSTILE = '<script>alert("xss")</script> & "quotes"'


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def build_corpus(path: Path):
    conn = db.connect(path)
    conn.execute("INSERT INTO raw_payload(sha256,url,fetched_at,path) VALUES('sha1','https://api.openalex.org/works?filter=' || 'x', '2026-09-03T00:00:00+00:00','harvest/raw/sh/sha1.json')")
    works = [
        ("W1", "Open Work", 2024, "cc-by", "an open abstract", "rendered"),
        ("W2", HOSTILE, 2023, "cc-by-nc-nd", None, "no-open-licence"),
        ("W3", "No Abstract Anywhere", 2010, None, None, "not-in-source"),
    ]
    for i, (wid, title, year, lic, abstract, reason) in enumerate(works):
        conn.execute(
            "INSERT INTO work(id,title,year,type,oa_license,abstract,abstract_reason,"
            "cited_by_count,referenced_count,is_seed,raw_sha,is_oa)"
            " VALUES(?,?,?,'article',?,?,?,?,?,1,'sha1',1)",
            (wid, title, year, lic, abstract, reason, 100 - i, 2),
        )
    for aid, name, orcid in [("A11", "Ada Lovelace", "0000-0002-1825-0097"),
                             ("A22", HOSTILE, None),
                             ("A33", "Solo Person", None)]:
        conn.execute(
            "INSERT INTO author(id,display_name,orcid,works_count,cited_by_count,raw_sha)"
            " VALUES(?,?,?,5,50,'sha1')", (aid, name, orcid))
    conn.execute("INSERT INTO institution(id,display_name) VALUES('I1','Somewhere')")
    for wid, aid, ordinal, pos in [("W1", "A11", 0, "first"), ("W1", "A22", 1, "last"),
                                   ("W2", "A11", 0, "first"), ("W2", "A33", 1, "last"),
                                   ("W3", "A33", 0, "first")]:
        conn.execute(
            "INSERT INTO authorship(work_id,author_id,ordinal,author_position,raw_name)"
            " VALUES(?,?,?,?,?)", (wid, aid, ordinal, pos, "Raw Name"))
        conn.execute(
            "INSERT OR IGNORE INTO affiliation(author_id,institution_id,work_id,year)"
            " VALUES(?,'I1',?,2020)", (aid, wid))
    conn.execute("INSERT INTO topic(id,display_name,field) VALUES('T1','Machine Learning','CS')")
    for citing, cited in [("W2", "W1"), ("W3", "W1"), ("W3", "W2")]:
        conn.execute("INSERT INTO citation(citing_id,cited_id) VALUES(?,?)", (citing, cited))
    for wid in ("W1", "W2", "W3"):
        conn.execute("INSERT INTO work_topic(work_id,topic_id,score) VALUES(?,'T1',0.9)", (wid,))
    graph.build_coauthorship(conn, 2026)
    derive.score_identities(conn)
    db.set_meta(conn, "derived_at", "2026-09-03T00:00:00+00:00")
    conn.commit()
    return conn


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
             render.DATA, render.SITE, render.ASSETS)
    try:
        dbp = tmp / "t.db"
        conn = build_corpus(dbp)

        # THE LEAK TEST, in two layers. First: the schema must refuse to store an
        # abstract beside a withholding reason at all.
        try:
            conn.execute("UPDATE work SET abstract = ? WHERE id = 'W2'", (SECRET,))
            bad += check(False, "the schema accepted text under a withholding reason")
        except sqlite3.IntegrityError:
            pass

        # Second: force the row past the constraint the way a corrupted or
        # migrated database could arrive, and prove the exporter still refuses.
        # A guard that only works because the writer is well behaved is not one.
        conn.execute("PRAGMA ignore_check_constraints = ON")
        conn.execute("UPDATE work SET abstract = ? WHERE id = 'W2'", (SECRET,))
        conn.commit()
        bad += check(
            conn.execute("SELECT abstract FROM work WHERE id='W2'").fetchone()["abstract"] == SECRET,
            "could not stage the leak, so the rest of this test proves nothing",
        )
        conn.close()

        export_json.OUT = tmp / "data"
        export_json.DB_PATH = dbp
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "export failed")

        blob = "".join(p.read_text() for p in (tmp / "data").rglob("*.json"))
        bad += check(SECRET not in blob, "AN UNLICENSED ABSTRACT REACHED THE EXPORTED JSON")

        works = json.loads((tmp / "data" / "works-index.json").read_text())
        authors = json.loads((tmp / "data" / "authors-index.json").read_text())
        bad += check(len(works) == 3 and len(authors) == 3, f"{len(works)} works, {len(authors)} authors")

        # Sharding must spread. This is the defect that put 5,332 of 6,906
        # authors in one file, and it was invisible until someone listed by size.
        shards = [len(json.loads(p.read_text())) for p in (tmp / "data" / "authors").glob("*.json")]
        bad += check(max(shards) <= max(2, int(len(authors) * 0.6)),
                     f"one shard holds {max(shards)} of {len(authors)} authors")

        # Provenance is deduplicated: entities carry a hash, payloads.json holds
        # the URL exactly once.
        payloads = json.loads((tmp / "data" / "payloads.json").read_text())
        bad += check(list(payloads) == ["sha1"], f"payload map: {list(payloads)}")
        w1 = json.loads((tmp / "data" / "works" / f"{export_json.shard('W1')}.json").read_text())["W1"]
        bad += check(w1["raw"] == "sha1", "work does not name its payload")
        bad += check("url" not in json.dumps(w1["raw"]), "the URL was inlined again")

        # Templates ship with the data, so the reader never keeps its own copy.
        corpus = json.loads((tmp / "data" / "corpus.json").read_text())
        bad += check("identity_notes" in corpus and "identity_bands" in corpus,
                     "corpus.json does not carry the evidence templates")

        # -- render --------------------------------------------------------
        render.DATA = tmp / "data"
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "render failed")

        html = "".join(p.read_text() for p in (tmp / "site").rglob("*.html"))
        bad += check(SECRET not in html, "AN UNLICENSED ABSTRACT REACHED THE RENDERED SITE")
        bad += check("no open licence" in html or "does not permit" in html,
                     "the withheld reason is not shown to the reader")

        # Escaping. A title containing markup must never become markup.
        bad += check("<script>alert" not in html, "a hostile title was rendered as markup")
        bad += check("&lt;script&gt;" in html, "the hostile title was dropped rather than escaped")

        # Every internal link has to land on a file that exists. This is the
        # check that catches a relative-path mistake, which is otherwise only
        # visible by clicking around a built site.
        site = tmp / "site"
        broken = []
        for page_path in site.rglob("*.html"):
            for href in re.findall(r'href="([^"#]+)"', page_path.read_text()):
                if href.startswith(("http", "mailto:", "//")):
                    continue
                target = (page_path.parent / href).resolve()
                if target.is_dir():
                    target = target / "index.html"
                if not target.exists():
                    broken.append(f"{page_path.relative_to(site)} -> {href}")
        bad += check(not broken, f"broken internal links: {broken[:4]}")

        # The graph is in the markup, not fetched by script: a crawler and a
        # reader with JavaScript off must both see it.
        w1_html = (site / "w" / "W1" / "index.html").read_text()
        bad += check("<svg" in w1_html, "the work page shipped no inline SVG")

        # Sitemap covers everything that was rendered.
        sitemap = (site / "sitemap.xml").read_text()
        for wid in ("W1", "W2", "W3"):
            bad += check(f"/w/{wid}/" in sitemap, f"{wid} missing from the sitemap")
    finally:
        (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
         render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_pipeline:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
