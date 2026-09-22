#!/usr/bin/env python3
"""End to end for Europe PMC's title/venue/date comparison inside `record_comparison`.

Stages a synthetic raw store the way `test_europepmc_work_assertions.py` and
`test_crossref_comparison.py` do, so the Europe PMC assertions t1's derive.py
already writes (europepmc_work_assertion) can be watched reaching the JSON
export via `export_json._record_comparison`, which previously read only
Crossref and returned `None` whenever no Crossref envelope existed.
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

# Fields Europe PMC's search result carries but that must never leave the
# assertion table or the exported JSON -- only title, venue and date do.
HOSTILE_ABSTRACT = "EuropePMCAbstractMustNotLeak4b2e"
HOSTILE_AUTHOR = "EuropePMCOnlyAuthorMustNotLeak8a1f"
HOSTILE_FULLTEXT = "https://example.org/europepmc-fulltext-must-not-leak.pdf"


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
            "fetched_at": "2026-09-19T00:00:00+00:00",
            "path": str(path.relative_to(root)),
        }, sort_keys=True) + "\n")
    return sha


def openalex_work(wid: str, doi: str, title: str, venue: str, year: int, date: str) -> dict:
    return {
        "id": f"https://openalex.org/{wid}",
        "doi": doi,
        "title": title,
        "publication_year": year,
        "publication_date": date,
        "type": "article",
        "cited_by_count": 3,
        "referenced_works": [],
        "primary_location": {
            "source": {"id": "https://openalex.org/S1", "display_name": venue},
        },
    }


def crossref_envelope(doi: str, title: str, venue: str, date_parts: list[int]) -> dict:
    return {
        "status": "ok",
        "message-type": "work",
        "message": {
            "DOI": doi,
            "type": "journal-article",
            "container-title": [venue],
            "title": [title],
            "issued": {"date-parts": [date_parts]},
        },
    }


def europepmc_search(result_id: str, doi: str, title: str, journal: str, abbrev: str,
                      pub_date: str, **extra) -> dict:
    result = {
        "id": result_id,
        "source": "MED",
        "doi": doi,
        "title": title,
        "journalInfo": {
            "journal": {"title": journal, "medlineAbbreviation": abbrev},
            "printPublicationDate": pub_date,
        },
        "firstPublicationDate": pub_date,
    }
    result.update(extra)
    return {
        "version": "6.9",
        "hitCount": 1,
        "request": {"queryString": f'DOI:"{doi}"', "resultType": "core"},
        "resultList": {"result": [result]},
    }


# W1: OpenAlex, Crossref and Europe PMC all agree -- every field should carry
# all three per-source entries and an "agree" status.
# W2: Europe PMC only -- no Crossref envelope at all.
# W3: neither Crossref nor Europe PMC assert anything about this work.
WORKS = {
    "W1": ("10.5555/w1", "Deep Learning And Cats", "Journal of Testing", 2020, "2020-03-15"),
    "W2": ("10.5555/w2", "Europe PMC Only Work", "Journal of Testing", 2021, "2021-06-01"),
    "W3": ("10.5555/w3", "No Comparison Work", "Journal of Testing", 2019, "2019-01-01"),
}


def stage(tmp: Path) -> dict[str, str]:
    shas = {}
    for wid, (doi, title, venue, year, date) in WORKS.items():
        shas[wid] = store_payload(
            tmp,
            {"results": [openalex_work(wid, f"https://doi.org/{doi}", title, venue, year, date)]},
            f"file://openalex-{wid}",
        )

    shas["crossref-W1"] = store_payload(
        tmp,
        crossref_envelope("10.5555/w1", "Deep Learning And Cats", "Journal of Testing", [2020, 3, 15]),
        "file://crossref-w1",
    )
    shas["europepmc-W1"] = store_payload(
        tmp,
        europepmc_search(
            "38000001", "10.5555/w1", "Deep Learning And Cats", "Journal of Testing", "J Test",
            "2020-03-15", abstractText=HOSTILE_ABSTRACT, authorString=HOSTILE_AUTHOR,
            fullTextUrlList={"fullTextUrl": [{"url": HOSTILE_FULLTEXT}]},
        ),
        "file://europepmc-w1",
    )
    shas["europepmc-W2"] = store_payload(
        tmp,
        europepmc_search(
            "38000002", "10.5555/w2", "Europe PMC Only Work", "Journal of Testing", "J Test",
            "2021-06-01",
        ),
        "file://europepmc-w2",
    )
    return shas


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH, export_json.ROOT)
    try:
        shas = stage(tmp)
        derive.RAW = tmp / "raw"
        derive.MANIFEST = tmp / "manifest.jsonl"

        conn = db.connect(tmp / "corpus.db")
        stats = derive.load(conn)
        bad += check(stats["crossref_assertions"] == 1,
                     f"expected one Crossref assertion, counted {stats['crossref_assertions']}")
        bad += check(stats["europepmc_assertions"] == 2,
                     f"expected two Europe PMC assertions, counted {stats['europepmc_assertions']}")

        derive.score_quality(conn)
        derive.score_identities(conn)
        db.set_meta(conn, "derived_at", "2026-09-19T00:00:00+00:00")
        conn.commit()
        conn.close()

        export_json.OUT = tmp / "data"
        export_json.DB_PATH = tmp / "corpus.db"
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "export failed")

        works = {}
        for path in (tmp / "data" / "works").glob("*.json"):
            works.update(json.loads(path.read_text()))
        payloads = json.loads((tmp / "data" / "payloads.json").read_text())
        corpus = json.loads((tmp / "data" / "corpus.json").read_text())

        # -- W1: Crossref + Europe PMC + OpenAlex all agree ---------------------
        comparison = works["W1"].get("record_comparison")
        bad += check(comparison is not None, "W1 (Crossref + Europe PMC) exported no record comparison")
        if comparison:
            for field in ("title", "venue", "date"):
                block = comparison.get(field)
                bad += check(block is not None, f"W1 record comparison is missing its {field} block")
                if not block:
                    continue
                bad += check(block["status"] == "agree",
                             f"W1 {field} status is {block.get('status')!r}, expected agree")
                for source in ("openalex", "crossref", "europepmc"):
                    bad += check(source in block, f"W1 {field} block is missing the {source} entry")
                bad += check(block.get("crossref", {}).get("raw") == shas["crossref-W1"],
                             f"W1 {field} crossref entry names the wrong payload")
                bad += check(block.get("europepmc", {}).get("raw") == shas["europepmc-W1"],
                             f"W1 {field} europepmc entry names the wrong payload, not the Crossref one")
                bad += check(block.get("openalex", {}).get("raw") == shas["W1"],
                             f"W1 {field} openalex entry names the wrong payload")
            bad += check(comparison["date"].get("precision") == "day",
                         f"W1 date precision is {comparison['date'].get('precision')!r}, expected day")

        # -- W2: Europe PMC only -- must now export a comparison at all ---------
        comparison = works["W2"].get("record_comparison")
        bad += check(comparison is not None,
                     "W2 (Europe PMC only, no Crossref) exported no record comparison at all")
        if comparison:
            for field in ("title", "venue", "date"):
                block = comparison.get(field)
                bad += check(block is not None, f"W2 record comparison is missing its {field} block")
                if not block:
                    continue
                bad += check("openalex" in block, f"W2 {field} block is missing the openalex entry")
                bad += check("europepmc" in block, f"W2 {field} block is missing the europepmc entry")
                bad += check("crossref" not in block,
                             f"W2 {field} block carries a crossref entry despite no Crossref envelope")
                bad += check(block.get("europepmc", {}).get("raw") == shas["europepmc-W2"],
                             f"W2 {field} europepmc entry names the wrong payload")

        # -- W3: neither source -- still None ------------------------------------
        bad += check(works["W3"].get("record_comparison") is None,
                     "W3 (no Crossref, no Europe PMC) exported a record comparison anyway")

        # -- Europe PMC's metadata role is declared in corpus.json ---------------
        metadata_sources = corpus.get("metadata_sources") or {}
        bad += check("europepmc" in metadata_sources,
                     "corpus.json does not declare Europe PMC's metadata role")
        europepmc_role = metadata_sources.get("europepmc", {}).get("role", "")
        bad += check(bool(europepmc_role), "Europe PMC's declared metadata role is empty")

        # -- no field beyond title/venue/date reaches the JSON -------------------
        json_blob = json.dumps(works)
        for hostile in (HOSTILE_ABSTRACT, HOSTILE_AUTHOR, HOSTILE_FULLTEXT):
            bad += check(hostile not in json_blob, f"{hostile!r} REACHED THE EXPORTED JSON")

        # payload hashes referenced by the comparison must resolve in payloads.json
        for wid in ("W1", "W2"):
            comparison = works[wid]["record_comparison"]
            for field in ("title", "venue", "date"):
                for source, entry in comparison[field].items():
                    if source == "status" or not isinstance(entry, dict):
                        continue
                    bad += check(entry["raw"] in payloads,
                                 f"{wid} {field} {source} hash {entry['raw']} does not resolve in payloads.json")
    finally:
        derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH, export_json.ROOT = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_europepmc_comparison_export:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
