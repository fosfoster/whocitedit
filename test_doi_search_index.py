#!/usr/bin/env python3
"""Offline coverage for DOI aliases in the compact global search index."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import db
import derive
import export_json
import render
import test_entity_export


DOI = "https://doi.org/10.5555/Resolver-Form"
ABSTRACT = "This synthetic abstract must never enter the compact search index."


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH,
             export_json.ROOT, render.DATA, render.SITE, render.ASSETS)
    try:
        db_path, _, _ = test_entity_export.build_corpus(tmp)
        conn = db.connect(db_path)
        conn.execute(
            "UPDATE work SET doi = ?, abstract = ?, abstract_reason = 'rendered' WHERE id = 'W1'",
            (DOI, ABSTRACT),
        )
        conn.commit()
        conn.close()

        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "synthetic export failed")

        works_index = json.loads((export_json.OUT / "works-index.json").read_text())
        works_by_id = {row["id"]: row for row in works_index}
        bad += check(works_by_id["W1"].get("doi") == DOI,
                     "work browse index did not preserve the stored resolver-form DOI")
        bad += check(all("doi" not in works_by_id[wid] for wid in ("W2", "W3")),
                     "DOI-less work browse rows gained a DOI field")

        render.DATA = export_json.OUT
        render.SITE = tmp / "site"
        render.ASSETS = Path(__file__).parent / "web" / "assets"
        bad += check(render.main() == 0, "synthetic render failed")

        search_path = render.SITE / "data" / "search-index.json"
        first = search_path.read_bytes()
        records = json.loads(first)
        work_records = {row["id"]: row for row in records if row["kind"] == "work"}
        w1_fields = works_by_id["W1"]["fields"]
        bad += check(work_records["W1"] == {
            "kind": "work", "id": "W1", "label": "Most Cited Work",
            "state": "complete", "aliases": [DOI], "fields": w1_fields,
        }, "DOI-bearing work search record changed its contract or alias")
        bad += check(all("aliases" not in work_records[wid] for wid in ("W2", "W3")),
                     "DOI-less work search records gained aliases")
        bad += check(all("aliases" not in row for row in records if row["kind"] != "work"),
                     "a non-work search record gained aliases")
        bad += check(ABSTRACT.encode() not in first,
                     "compact search index exposed abstract text")
        bad += check(list((render.SITE / "data").glob("*search*.json")) == [search_path],
                     "render created more than one search index")
        bad += check((render.SITE / "w" / "W1" / "index.html").exists(),
                     "DOI-bearing work lost its canonical /w/W1/ page")

        bad += check(render.main() == 0, "second synthetic render failed")
        bad += check(first == search_path.read_bytes(),
                     "global search index is not deterministic across renders")
    finally:
        (derive.RAW, derive.MANIFEST, export_json.OUT, export_json.DB_PATH,
         export_json.ROOT, render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_doi_search_index:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
