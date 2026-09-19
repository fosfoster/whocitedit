#!/usr/bin/env python3
"""Every work rendered by render.py gets a citation.csl.json beside its page.

Runs the static renderer over the synthetic fixture corpus and holds the
generated artifacts to the CSL-JSON contract: one file per rendered work
detail page -- DOI or not -- each parsing as JSON carrying id, type and title
taken from that work's own metadata.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import render
import test_entity_export


CSL_JSON = "citation.csl.json"

# One work with a DOI and two without, so the DOI-less case is covered, and
# three distinct types, so a type copied from metadata is distinguishable from
# a constant.
FIXTURE_METADATA = {
    "W1": {"doi": "https://doi.org/10.1000/synthetic-w1", "type": "article"},
    "W2": {"doi": None, "type": "book"},
    "W3": {"doi": None, "type": "dataset"},
}


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def load_works(data: Path) -> dict:
    works = {}
    for path in sorted((data / "works").glob("*.json")):
        works.update(json.loads(path.read_text()))
    return works


def update_works(data: Path, changes: dict) -> None:
    for path in sorted((data / "works").glob("*.json")):
        payload = json.loads(path.read_text())
        touched = False
        for wid, fields in changes.items():
            if wid in payload:
                payload[wid].update(fields)
                touched = True
        if touched:
            path.write_text(json.dumps(payload, sort_keys=True))


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (render.DATA, render.SITE, render.ASSETS)
    try:
        db_path, _, _ = test_entity_export.build_corpus(tmp)
        import export_json

        export_saved = (export_json.OUT, export_json.DB_PATH, export_json.ROOT)
        try:
            export_json.OUT = tmp / "data"
            export_json.DB_PATH = db_path
            export_json.ROOT = Path(__file__).parent
            bad += check(export_json.main() == 0, "synthetic export failed")
        finally:
            (export_json.OUT, export_json.DB_PATH, export_json.ROOT) = export_saved

        data = tmp / "data"
        update_works(data, FIXTURE_METADATA)
        works = load_works(data)
        bad += check(set(works) == set(FIXTURE_METADATA),
                     "synthetic export did not produce the expected fixture works")
        no_doi = sorted(wid for wid, w in works.items() if not w.get("doi"))
        bad += check(no_doi, "fixture corpus has no work without a DOI to cover")

        render.DATA = data
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "synthetic render failed")

        pages = sorted((render.SITE / "w").glob("*/index.html"))
        bad += check({page.parent.name for page in pages} == set(works),
                     "rendered work pages are not exactly the exported works")

        emitted_types = {}
        for page in pages:
            wid = page.parent.name
            artifact = page.parent / CSL_JSON
            missing = check(artifact.exists(), f"no {CSL_JSON} beside the rendered page for {wid}")
            bad += missing
            if missing:
                continue
            try:
                item = json.loads(artifact.read_text(encoding="utf-8"))
            except ValueError as exc:
                bad += check(False, f"{wid} {CSL_JSON} is not valid JSON: {exc}")
                continue
            bad += check(isinstance(item, dict), f"{wid} {CSL_JSON} is not a CSL-JSON item object")
            if not isinstance(item, dict):
                continue
            work = works[wid]
            bad += check(item.get("id") == wid, f"{wid} {CSL_JSON} id is not the work id")
            bad += check(item.get("title") == work["title"],
                         f"{wid} {CSL_JSON} title is not the work's exported title")
            bad += check(isinstance(item.get("type"), str) and item["type"],
                         f"{wid} {CSL_JSON} has no populated type")
            emitted_types[wid] = item.get("type")

        bad += check(len(set(emitted_types.values())) == len(FIXTURE_METADATA),
                     "works with different exported types emitted the same CSL type")

        for wid in no_doi:
            artifact = render.SITE / "w" / wid / CSL_JSON
            bad += check(artifact.exists(),
                         f"no-DOI work {wid} did not get a {CSL_JSON} artifact")
            if artifact.exists():
                item = json.loads(artifact.read_text(encoding="utf-8"))
                bad += check("DOI" not in item,
                             f"no-DOI work {wid} emitted a DOI field anyway")
    finally:
        (render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_csl_json_generation:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
