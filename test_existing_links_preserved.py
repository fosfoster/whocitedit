#!/usr/bin/env python3
"""Regression coverage: the five pre-existing Links panel entries (BibTeX, RIS,
DOI, open-access copy, OpenAlex record) must stay present and unchanged under
their original conditions, independent of any CSL-JSON link added alongside
them.
"""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import export_json
import render
import test_entity_export


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def update_work(data: Path, wid: str, **changes) -> None:
    for path in (data / "works").glob("*.json"):
        payload = json.loads(path.read_text())
        if wid in payload:
            payload[wid].update(changes)
            path.write_text(json.dumps(payload, sort_keys=True))
            return
    raise KeyError(wid)


def links_panel(page: str) -> str:
    match = re.search(r"<h2>Links</h2>\s*<p>(.*?)</p>", page, re.DOTALL)
    return match.group(1) if match else ""


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
             render.DATA, render.SITE, render.ASSETS)
    try:
        db_path, _, _ = test_entity_export.build_corpus(tmp)
        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "synthetic export failed")

        data = tmp / "data"
        # W1: has both a DOI and an open-access copy.
        update_work(
            data, "W1", doi="https://doi.org/10.1000/with-doi",
            oa={"url": "https://example.test/W1.pdf", "license": None},
        )
        # W2: no DOI, but has an open-access copy.
        update_work(
            data, "W2", doi=None,
            oa={"url": "https://example.test/W2.pdf", "license": None},
        )
        # W3: has a DOI, but no open-access copy.
        update_work(
            data, "W3", doi="https://doi.org/10.1000/another-doi",
            oa={"url": None, "license": None},
        )

        render.DATA = data
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "synthetic render failed")

        expected = {
            "W1": {
                "bibtex": True,
                "ris": True,
                "doi": '<a href="https://doi.org/10.1000/with-doi">DOI</a>',
                "oa": '<a href="https://example.test/W1.pdf">Open access copy</a>',
            },
            "W2": {
                "bibtex": True,
                "ris": True,
                "doi": None,
                "oa": '<a href="https://example.test/W2.pdf">Open access copy</a>',
            },
            "W3": {
                "bibtex": True,
                "ris": True,
                "doi": '<a href="https://doi.org/10.1000/another-doi">DOI</a>',
                "oa": None,
            },
        }

        for wid, want in expected.items():
            detail = render.SITE / "w" / wid / "index.html"
            page = detail.read_text(encoding="utf-8") if detail.exists() else ""
            panel = links_panel(page)
            bad += check(bool(panel), f"{wid} has no Links panel")

            # BibTeX
            bibtex_links = re.findall(
                r'<a href="([^"]+)" download>Download BibTeX</a>', panel,
            )
            bad += check(len(bibtex_links) == 1,
                         f"{wid} does not have exactly one BibTeX download link")
            if len(bibtex_links) == 1:
                href = bibtex_links[0]
                bad += check(href == "citation.bib", f"{wid} BibTeX link is not relative")
                target = (detail.parent / href).resolve()
                expected_target = (render.SITE / "w" / wid / "citation.bib").resolve()
                bad += check(target == expected_target and target.exists(),
                             f"{wid} BibTeX link does not resolve to its static citation file")

            # RIS
            ris_links = re.findall(
                r'<a href="([^"]+)" download>Download RIS</a>', panel,
            )
            bad += check(len(ris_links) == 1,
                         f"{wid} does not have exactly one RIS download link")
            if len(ris_links) == 1:
                href = ris_links[0]
                bad += check(href == "citation.ris", f"{wid} RIS link is not relative")
                target = (detail.parent / href).resolve()
                expected_target = (render.SITE / "w" / wid / "citation.ris").resolve()
                bad += check(target == expected_target and target.exists(),
                             f"{wid} RIS link does not resolve to its static citation file")

            # DOI
            if want["doi"] is not None:
                bad += check(want["doi"] in panel, f"{wid} lost its DOI link")
            else:
                bad += check(
                    '<a href="https://doi.org/' not in panel,
                    f"{wid} has no DOI in its source record but emitted a DOI link",
                )

            # Open-access copy
            if want["oa"] is not None:
                bad += check(want["oa"] in panel, f"{wid} lost its open-access copy link")
            else:
                bad += check(
                    'Open access copy</a>' not in panel,
                    f"{wid} has no open-access copy in its source record but emitted one",
                )

            # OpenAlex record
            openalex_link = f'<a href="https://openalex.org/{wid}">OpenAlex record</a>'
            bad += check(openalex_link in panel, f"{wid} lost its OpenAlex record link")
    finally:
        (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
         render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_existing_links_preserved:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
