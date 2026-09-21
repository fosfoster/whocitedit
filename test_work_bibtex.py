#!/usr/bin/env python3
"""Offline coverage for static BibTeX files beside rendered work pages."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import export_json
import render
import test_pipeline


ABSTRACT_SENTINEL = "BIBTEX_ABSTRACT_MUST_NOT_APPEAR"
OTHER_SOURCE_SENTINEL = "BIBTEX_OTHER_SOURCE_MUST_NOT_APPEAR"


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def payloads(data: Path):
    works = {}
    for shard in (data / "works").glob("*.json"):
        works.update(json.loads(shard.read_text()))
    return works


def main() -> int:
    bad = 0

    complete = {
        "id": "W123",
        "title": "Café & # $ % _ { } ~ ^ \\ <title>",
        "year": 2024,
        "source": {"name": "Source & Proceedings"},
        "doi": "https://doi.org/10.1000/a_b",
        "authors": [{"name": "Second Author"}, {"name": "First Author"}],
        "abstract": {"text": ABSTRACT_SENTINEL},
        "oa": {"url": OTHER_SOURCE_SENTINEL},
        "openalex_url": OTHER_SOURCE_SENTINEL,
    }
    expected = (
        "@misc{W123,\n"
        "  author = {Second Author and First Author},\n"
        "  title = {Café \\& \\# \\$ \\% \\_ \\{ \\} \\textasciitilde{} "
        "\\textasciicircum{} \\textbackslash{} <title>},\n"
        "  year = {2024},\n"
        "  howpublished = {Source \\& Proceedings},\n"
        "  doi = {https://doi.org/10.1000/a\\_b}\n"
        "}\n"
    )
    bad += check(render.work_bibtex(complete) == expected,
                 "complete BibTeX entry lost order, UTF-8, or BibTeX escaping")
    bad += check(render.work_bibtex(complete) == render.work_bibtex(complete),
                 "BibTeX serialization is not byte-stable")
    sparse = {"id": "W-empty", "title": None, "year": None, "source": {},
              "doi": None, "authors": [], "abstract": {"text": ABSTRACT_SENTINEL}}
    bad += check(render.work_bibtex(sparse) == "@misc{W-empty,\n}\n",
                 "sparse work did not omit absent fields")
    bad += check(ABSTRACT_SENTINEL not in render.work_bibtex(complete)
                 and ABSTRACT_SENTINEL not in render.work_bibtex(sparse),
                 "abstract entered the BibTeX formatter")
    bad += check(OTHER_SOURCE_SENTINEL not in render.work_bibtex(complete),
                 "a field outside the rendered citation sources entered the BibTeX formatter")

    tmp = Path(tempfile.mkdtemp())
    saved = (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
             render.DATA, render.SITE, render.ASSETS)
    try:
        db_path = tmp / "fixture.db"
        conn = test_pipeline.build_corpus(db_path)
        conn.execute(
            "UPDATE work SET title = ?, doi = ?, source_name = ?, abstract = ? WHERE id = 'W1'",
            (complete["title"], complete["doi"], complete["source"]["name"], ABSTRACT_SENTINEL),
        )
        conn.execute("UPDATE author SET display_name = ? WHERE id = 'A11'", ("Second Author",))
        conn.execute("UPDATE author SET display_name = ? WHERE id = 'A22'", ("First Author",))
        conn.execute("DELETE FROM authorship WHERE work_id = 'W2'")
        conn.execute("UPDATE work SET year = NULL, doi = NULL, source_name = NULL WHERE id = 'W2'")
        conn.commit()
        conn.close()

        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "export fixture failed")

        render.DATA = tmp / "data"
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "temporary render failed")
        works = payloads(tmp / "data")
        citations = list((tmp / "site" / "w").glob("*/citation.bib"))
        bad += check(len(citations) == len(works), "not every rendered work has one citation file")
        for wid, work in works.items():
            citation = tmp / "site" / "w" / wid / "citation.bib"
            bad += check(citation.exists(), f"{wid} has no citation.bib")
            if citation.exists():
                text = citation.read_text(encoding="utf-8")
                bad += check(text == render.work_bibtex(work), f"{wid} citation differs from its page data")
                bad += check(ABSTRACT_SENTINEL not in text, f"{wid} citation leaked an abstract")

        # The fixture corpus stores every work as type='article', so the rendered
        # entries open with @article where the untyped works above open with @misc.
        # Everything after that first line is the same escaping and order.
        rendered = (tmp / "site" / "w" / "W1" / "citation.bib").read_text(encoding="utf-8")
        bad += check(rendered == expected.replace("@misc{W123", "@article{W1", 1),
                     "rendered complete citation has the wrong entry type, fields, or escaping")
        sparse_rendered = (tmp / "site" / "w" / "W2" / "citation.bib").read_text(encoding="utf-8")
        bad += check(sparse_rendered == "@article{W2,\n  title = {<script>alert(\"xss\")</script> \\& \"quotes\"}\n}\n",
                     "rendered sparse citation fabricated absent fields")
    finally:
        (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
         render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_work_bibtex:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
