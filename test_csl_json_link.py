#!/usr/bin/env python3
"""Offline coverage for CSL-JSON download links on rendered work pages."""
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
        update_work(
            data, "W1", doi="https://doi.org/10.1000/with-doi",
            oa={"url": "https://example.test/W1.pdf", "license": None},
        )
        update_work(
            data, "W2", doi=None,
            oa={"url": "https://example.test/W2.pdf", "license": None},
        )
        update_work(
            data, "W3", doi="https://doi.org/10.1000/another-doi",
            oa={"url": None, "license": None},
        )

        render.DATA = data
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "synthetic render failed")

        expected_external = {
            "W1": [
                '<a href="https://doi.org/10.1000/with-doi">DOI</a>',
                '<a href="https://example.test/W1.pdf">Open access copy</a>',
            ],
            "W2": ['<a href="https://example.test/W2.pdf">Open access copy</a>'],
            "W3": ['<a href="https://doi.org/10.1000/another-doi">DOI</a>'],
        }

        for wid in ("W1", "W2", "W3"):
            detail = render.SITE / "w" / wid / "index.html"
            page = detail.read_text(encoding="utf-8") if detail.exists() else ""
            panel = links_panel(page)
            bad += check(bool(panel), f"{wid} has no Links panel")

            csl_links = re.findall(
                r'<a href="([^"]+)" download>Download CSL-JSON</a>', panel,
            )
            bad += check(len(csl_links) == 1,
                         f"{wid} does not have exactly one CSL-JSON download link")
            if len(csl_links) == 1:
                href = csl_links[0]
                bad += check(not href.startswith(("/", "http")),
                             f"{wid} CSL-JSON link is not relative")
                target = (detail.parent / href).resolve()
                bad += check(target.exists(),
                             f"{wid} CSL-JSON link does not resolve to a static file")
                if target.exists():
                    payload = json.loads(target.read_text(encoding="utf-8"))
                    bad += check(payload.get("id") == wid,
                                 f"{wid} CSL-JSON link target is not that work's CSL-JSON")

            bibtex_links = re.findall(
                r'<a href="([^"]+)" download>Download BibTeX</a>', panel,
            )
            bad += check(len(bibtex_links) == 1,
                         f"{wid} does not have exactly one BibTeX download link")
            if len(bibtex_links) == 1:
                bad += check(bibtex_links[0] == "citation.bib",
                             f"{wid} BibTeX link is not relative")
                target = (detail.parent / bibtex_links[0]).resolve()
                bad += check(target.exists(),
                             f"{wid} BibTeX link does not resolve to its static citation file")

            ris_links = re.findall(
                r'<a href="([^"]+)" download>Download RIS</a>', panel,
            )
            bad += check(len(ris_links) == 1,
                         f"{wid} does not have exactly one RIS download link")
            if len(ris_links) == 1:
                bad += check(ris_links[0] == "citation.ris",
                             f"{wid} RIS link is not relative")
                target = (detail.parent / ris_links[0]).resolve()
                bad += check(target.exists(),
                             f"{wid} RIS link does not resolve to its static citation file")

            for link in expected_external[wid]:
                bad += check(link in panel, f"{wid} lost external link: {link}")
            bad += check(
                f'<a href="https://openalex.org/{wid}">OpenAlex record</a>' in panel,
                f"{wid} lost its OpenAlex link",
            )
    finally:
        (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
         render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_csl_json_link:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
