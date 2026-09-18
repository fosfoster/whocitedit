#!/usr/bin/env python3
"""End to end for the Crossref title/date comparison: raw -> database -> JSON -> HTML.

Temporary by intent: it stages the whole pipeline over a synthetic raw store
so the additive Crossref assertion can be watched from the stored envelope to
the rendered page. Once the reader app owns this panel, the export-shape
checks belong in `test_entity_export.py` and the page checks beside the other
render tests.
"""
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import db
import derive
import export_json
import render

# Strings that must never leave the raw Crossref envelope. Each is unique so
# a grep of the exported JSON and rendered HTML is a sufficient leak test.
HOSTILE_ABSTRACT = "CrossrefAbstractMustNotLeak9f3a"
HOSTILE_AUTHOR = "CrossrefOnlyAuthorMustNotLeak7c1d"
HOSTILE_REFERENCE = "10.9999/crossref-reference-must-not-leak"
HOSTILE_FULLTEXT = "https://example.org/crossref-fulltext-must-not-leak.pdf"
HOSTILE_COUNT = 987654


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def store_payload(root: Path, payload, url: str) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sha = hashlib.sha256(body).hexdigest()
    path = root / "raw" / sha[:2] / f"{sha}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    with (root / "manifest.jsonl").open("a") as fh:
        fh.write(json.dumps({
            "sha256": sha,
            "url": url,
            "fetched_at": "2026-09-16T00:00:00+00:00",
            "path": str(path.relative_to(root)),
        }, sort_keys=True) + "\n")
    return sha


def openalex_work(wid: str, doi: str, title: str, year: int, date: str | None,
                  authors: list[str], references: list[str]) -> dict:
    return {
        "id": f"https://openalex.org/{wid}",
        "doi": doi,
        "title": title,
        "publication_year": year,
        "publication_date": date,
        "type": "article",
        "cited_by_count": 5,
        "referenced_works": [f"https://openalex.org/{r}" for r in references],
        "primary_location": {
            "source": {"id": "https://openalex.org/S1", "display_name": "Journal of Testing"},
        },
        "authorships": [
            {
                "author": {"id": f"https://openalex.org/{aid}", "display_name": f"Author {aid}"},
                "author_position": "first" if i == 0 else "last",
                "raw_author_name": f"Author {aid}",
            }
            for i, aid in enumerate(authors)
        ],
    }


def crossref_envelope(doi: str, title=None, date_parts=None, **extra) -> dict:
    message = {"DOI": doi, "type": "journal-article", "container-title": ["Journal of Testing"]}
    if title is not None:
        message["title"] = [title]
    if date_parts is not None:
        message["issued"] = {"date-parts": [date_parts]}
    message.update(extra)
    return {"status": "ok", "message-type": "work", "message": message}


HOSTILE_EXTRAS = {
    "abstract": f"<jats:p>{HOSTILE_ABSTRACT}</jats:p>",
    "author": [{"given": "Nobody", "family": HOSTILE_AUTHOR}],
    "reference": [{"DOI": HOSTILE_REFERENCE}],
    "is-referenced-by-count": HOSTILE_COUNT,
    "link": [{"URL": HOSTILE_FULLTEXT, "content-type": "application/pdf"}],
}

WORKS = {
    # agreeing: markup, entity, case and a trailing full stop differ, nothing else
    "W1": ("10.5555/w1", "Deep Learning & Cats", 2020, "2020-03-15"),
    # disagreeing on both title and full date
    "W2": ("10.5555/w2", "Original Title Two", 2019, "2019-06-01"),
    # Crossref supplies a year only; OpenAlex a full date
    "W3": ("10.5555/w3", "Partial Date Work", 2021, "2021-07-04"),
    # Crossref supplies neither title nor date
    "W4": ("10.5555/w4", "Missing Field Work", 2018, "2018-02-02"),
}

ENVELOPES = {
    "W1": crossref_envelope("10.5555/W1", "Deep <i>Learning</i> &amp; Cats.", [2020, 3, 15], **HOSTILE_EXTRAS),
    "W2": crossref_envelope("https://doi.org/10.5555/w2", "Completely Different Title", [2018, 1, 1]),
    "W3": crossref_envelope("10.5555/w3", "Partial Date Work", [2021]),
    "W4": crossref_envelope("10.5555/w4"),
    "outside": crossref_envelope("10.5555/not-in-corpus", "Nowhere Work", [2020, 1, 1]),
}


def stage(tmp: Path) -> dict[str, str]:
    shas = {}
    for wid, (doi, title, year, date) in WORKS.items():
        refs = ["W1"] if wid == "W2" else []
        authors = ["A1", "A2"] if wid == "W1" else ["A1"]
        shas[wid] = store_payload(
            tmp,
            {"results": [openalex_work(wid, f"https://doi.org/{doi}", title, year, date, authors, refs)]},
            f"file://openalex-{wid}",
        )
    for key, envelope in ENVELOPES.items():
        shas[f"crossref-{key}"] = store_payload(tmp, envelope, f"file://crossref-{key}")
    return shas


def load_assertions(conn) -> dict[str, tuple]:
    return {
        r["work_id"]: (r["raw_sha"], r["title"], r["published"])
        for r in conn.execute(
            "SELECT work_id, raw_sha, title, published FROM crossref_work_assertion ORDER BY work_id"
        )
    }


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (derive.RAW, derive.MANIFEST, derive._payloads,
             export_json.OUT, export_json.DB_PATH, export_json.ROOT,
             render.DATA, render.SITE, render.ASSETS)
    try:
        shas = stage(tmp)
        derive.RAW = tmp / "raw"
        derive.MANIFEST = tmp / "manifest.jsonl"

        # -- raw -> database, in two processing orders ------------------------
        conn = db.connect(tmp / "forward.db")
        stats = derive.load(conn)
        forward = load_assertions(conn)
        bad += check(stats["crossref_assertions"] == 4,
                     f"expected four DOI-matched Crossref assertions, counted {stats['crossref_assertions']}")

        natural = derive._payloads
        derive._payloads = lambda: reversed(list(natural()))
        reverse_conn = db.connect(tmp / "reverse.db")
        derive.load(reverse_conn)
        derive._payloads = natural
        bad += check(load_assertions(reverse_conn) == forward,
                     "DOI attachment changed with raw processing order")
        reverse_conn.close()

        bad += check(set(forward) == {"W1", "W2", "W3", "W4"},
                     f"assertion rows attached to {sorted(forward)}")
        bad += check(forward["W1"] == (shas["crossref-W1"], "Deep Learning & Cats.", "2020-03-15"),
                     f"W1 stored {forward['W1']!r}: title must be plain text, not normalized")
        bad += check(forward["W2"] == (shas["crossref-W2"], "Completely Different Title", "2018-01-01"),
                     f"W2 stored {forward['W2']!r}")
        bad += check(forward["W3"] == (shas["crossref-W3"], "Partial Date Work", "2021"),
                     f"W3 stored {forward['W3']!r}: a year-only date must not grow a month or day")
        bad += check(forward["W4"] == (shas["crossref-W4"], None, None),
                     f"W4 stored {forward['W4']!r}: missing fields must stay NULL")

        columns = {r["name"] for r in conn.execute("PRAGMA table_info(crossref_work_assertion)")}
        bad += check(
            not columns & {"abstract", "authors", "author", "reference", "references", "cited_by_count",
                           "is_referenced_by_count", "link", "full_text"},
            f"the assertion table grew a column it must not hold: {sorted(columns)}",
        )
        table_blob = json.dumps([dict(r) for r in conn.execute("SELECT * FROM crossref_work_assertion")])
        for hostile in (HOSTILE_ABSTRACT, HOSTILE_AUTHOR, HOSTILE_REFERENCE, HOSTILE_FULLTEXT, str(HOSTILE_COUNT)):
            bad += check(hostile not in table_blob, f"{hostile!r} reached the assertion table")

        # The authoritative row is untouched by a disagreement.
        for wid, (doi, title, year, date) in WORKS.items():
            row = conn.execute(
                "SELECT title, year, publication_date, cited_by_count FROM work WHERE id = ?", (wid,)
            ).fetchone()
            bad += check(
                (row["title"], row["year"], row["publication_date"]) == (title, year, date),
                f"{wid} work row was rewritten by Crossref: {tuple(row)}",
            )
            bad += check(row["cited_by_count"] == 5, f"{wid} citation count changed to {row['cited_by_count']}")

        citations = [tuple(r) for r in conn.execute("SELECT citing_id, cited_id FROM citation ORDER BY 1, 2")]
        bad += check(citations == [("W2", "W1")], f"citation rows changed: {citations}")
        authors = {r["id"]: r["display_name"] for r in conn.execute("SELECT id, display_name FROM author")}
        bad += check(authors == {"A1": "Author A1", "A2": "Author A2"}, f"author identities changed: {authors}")
        authorships = conn.execute("SELECT COUNT(*) c FROM authorship").fetchone()["c"]
        bad += check(authorships == 5, f"authorship count changed to {authorships}")

        derive.score_quality(conn)
        derive.score_identities(conn)
        db.set_meta(conn, "derived_at", "2026-09-16T00:00:00+00:00")
        conn.commit()
        conn.close()

        # -- database -> JSON --------------------------------------------------
        export_json.OUT = tmp / "data"
        export_json.DB_PATH = tmp / "forward.db"
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "export failed")

        works = {}
        for path in (tmp / "data" / "works").glob("*.json"):
            works.update(json.loads(path.read_text()))
        payloads = json.loads((tmp / "data" / "payloads.json").read_text())
        corpus = json.loads((tmp / "data" / "corpus.json").read_text())

        expected = {
            "W1": ("agree", "agree", "day"),
            "W2": ("disagree", "disagree", "day"),
            "W3": ("agree", "agree", "year"),
            "W4": ("unavailable", "unavailable", None),
        }
        for wid, (title_status, date_status, precision) in expected.items():
            work = works[wid]
            doi, title, year, date = WORKS[wid]
            bad += check((work["title"], work["year"], work["date"]) == (title, year, date),
                         f"{wid} exported OpenAlex record changed: {work['title']!r} {work['year']} {work['date']}")
            comparison = work.get("record_comparison")
            bad += check(comparison is not None, f"{wid} exported no record comparison")
            if not comparison:
                continue
            bad += check(comparison["title"]["status"] == title_status,
                         f"{wid} title status {comparison['title']['status']}, expected {title_status}")
            bad += check(comparison["date"]["status"] == date_status,
                         f"{wid} date status {comparison['date']['status']}, expected {date_status}")
            bad += check(comparison["date"].get("precision") == precision,
                         f"{wid} date precision {comparison['date'].get('precision')}, expected {precision}")
            for field in ("title", "date"):
                for source in ("openalex", "crossref"):
                    assertion = comparison[field][source]
                    bad += check(assertion["source"] == source, f"{wid} {field} assertion lost its source label")
                    bad += check(assertion["raw"] in payloads,
                                 f"{wid} {field} {source} hash {assertion['raw']} does not resolve in payloads.json")
                bad += check(comparison[field]["openalex"]["raw"] == shas[wid],
                             f"{wid} {field} OpenAlex assertion names the wrong payload")
                bad += check(comparison[field]["crossref"]["raw"] == shas[f"crossref-{wid}"],
                             f"{wid} {field} Crossref assertion names the wrong payload")
            bad += check(comparison["title"]["openalex"]["value"] == title,
                         f"{wid} OpenAlex title assertion was normalized or replaced")
            bad += check(comparison["date"]["openalex"]["value"] == date,
                         f"{wid} OpenAlex date assertion changed")
            bad += check("comparison" in comparison.get("role", ""),
                         f"{wid} comparison does not state Crossref's role")

        bad += check(works["W1"]["record_comparison"]["title"]["crossref"]["value"] == "Deep Learning & Cats.",
                     "W1's asserted Crossref title was exported normalized rather than as asserted")
        bad += check(works["W3"]["record_comparison"]["date"]["crossref"]["value"] == "2021",
                     "W3's year-only Crossref date was expanded on export")
        bad += check(works["W4"]["record_comparison"]["title"]["crossref"]["value"] is None
                     and works["W4"]["record_comparison"]["date"]["crossref"]["value"] is None,
                     "W4's missing Crossref fields were exported as something other than null")
        bad += check(shas["crossref-outside"] in payloads
                     and not any(sha == shas["crossref-outside"]
                                 for w in works.values() if w.get("record_comparison")
                                 for sha in (w["record_comparison"]["title"]["crossref"]["raw"],)),
                     "the unmatched-DOI envelope was attached to a work")
        crossref_role = (corpus.get("metadata_sources") or {}).get("crossref", {}).get("role", "")
        bad += check("title" in crossref_role and "date" in crossref_role,
                     f"corpus.json does not declare Crossref's title/date comparison role: {crossref_role!r}")
        bad += check(set(corpus["citation_sources"]) == {"openalex", "opencitations", "europepmc", "crossref"},
                     "citation-edge source declarations do not match the four declared indexes")

        for wid in expected:
            bad += check(len(works[wid]["authors"]) == (2 if wid == "W1" else 1),
                         f"{wid} exported author count changed")
            bad += check(works[wid]["cited_by_count"] == 5, f"{wid} exported citation count changed")
        w2_edges = {(edge["s"], edge["t"]) for edge in works["W2"]["graph"]["edges"]}
        bad += check(w2_edges == {("W2", "W1")}, f"W2 exported citation edges changed: {w2_edges}")

        json_blob = "".join(p.read_text() for p in (tmp / "data").rglob("*.json"))
        for hostile in (HOSTILE_ABSTRACT, HOSTILE_AUTHOR, HOSTILE_REFERENCE, HOSTILE_FULLTEXT, str(HOSTILE_COUNT)):
            bad += check(hostile not in json_blob, f"{hostile!r} REACHED THE EXPORTED JSON")

        # -- JSON -> HTML ------------------------------------------------------
        render.DATA = tmp / "data"
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "render failed")
        site = tmp / "site"
        html_blob = "".join(p.read_text() for p in site.rglob("*.html"))
        for hostile in (HOSTILE_ABSTRACT, HOSTILE_AUTHOR, HOSTILE_REFERENCE, HOSTILE_FULLTEXT, str(HOSTILE_COUNT)):
            bad += check(hostile not in html_blob, f"{hostile!r} REACHED THE RENDERED SITE")

        for wid, (title_status, date_status, precision) in expected.items():
            page = (site / "w" / wid / "index.html").read_text()
            doi, title, year, date = WORKS[wid]
            bad += check(f"<h1>{render.e(title)}</h1>" in page, f"{wid} page heading is not the OpenAlex title")
            bad += check("Title and date across sources" in page, f"{wid} page has no comparison panel")
            bad += check("<b>OpenAlex</b>:" in page and "<b>Crossref</b>:" in page,
                         f"{wid} page does not label both sources")
            bad += check(f'<span class="badge {title_status}">{title_status}</span> <span>Title</span>' in page,
                         f"{wid} page does not show the title comparison as {title_status}")
            bad += check(
                f'<span class="badge {date_status}">{date_status}</span> <span>Publication date</span>' in page,
                f"{wid} page does not show the date comparison as {date_status}",
            )
            if precision:
                bad += check(f"compared to the {precision}" in page,
                             f"{wid} page does not say the date was compared to the {precision}")
            bad += check(shas[wid] in page and shas[f"crossref-{wid}"] in page,
                         f"{wid} page does not show both payload hashes")
        w1_page = (site / "w" / "W1" / "index.html").read_text()
        bad += check("Deep Learning &amp; Cats." in w1_page,
                     "W1 page does not show Crossref's title as asserted")
        bad += check("not asserted" in (site / "w" / "W4" / "index.html").read_text(),
                     "W4 page hides that Crossref asserted nothing")
        bad += check(">2021<" in (site / "w" / "W3" / "index.html").read_text()
                     or "2021 <span" in (site / "w" / "W3" / "index.html").read_text(),
                     "W3 page does not show the year-only Crossref date")
    finally:
        (derive.RAW, derive.MANIFEST, derive._payloads,
         export_json.OUT, export_json.DB_PATH, export_json.ROOT,
         render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_crossref_comparison:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
