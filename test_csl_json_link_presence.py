#!/usr/bin/env python3
"""Offline coverage for CSL-JSON download links on rendered work pages.

Also pins the other Links-panel entries to the conditions they carried before
the CSL-JSON link was added: BibTeX and RIS unconditional, DOI only with a DOI,
the open-access copy only with an open-access URL, OpenAlex always.
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


DOIS = {
    "W1": "https://doi.org/10.1000/with-doi",
    "W3": "https://doi.org/10.1000/another-doi",
}
OA_URLS = {
    "W1": "https://repo.example.org/W1.pdf",
    "W2": "https://repo.example.org/W2.pdf",
}
# One work per DOI/open-access combination, split across two renders so all
# four are covered by the three fixture works.
SCENARIOS = [
    {"W1": ("W1", "W1"), "W2": (None, None), "W3": ("W3", None)},
    {"W1": ("W1", "W1"), "W2": (None, "W2"), "W3": ("W3", None)},
]


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


def expected_links(doi, oa_url, wid: str) -> list:
    links = [
        '<a href="citation.bib" download>Download BibTeX</a>',
        '<a href="citation.ris" download>Download RIS</a>',
        '<a href="citation.csl.json" download>Download CSL-JSON</a>',
    ]
    if doi:
        links.append(f'<a href="{doi}">DOI</a>')
    if oa_url:
        links.append(f'<a href="{oa_url}">Open access copy</a>')
    links.append(f'<a href="https://openalex.org/{wid}">OpenAlex record</a>')
    return links


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
        render.DATA = data

        for n, scenario in enumerate(SCENARIOS):
            for wid, (doi_key, oa_key) in scenario.items():
                update_work(
                    data, wid,
                    doi=DOIS[doi_key] if doi_key else None,
                    oa={
                        "is_oa": bool(oa_key),
                        "status": "green" if oa_key else "closed",
                        "url": OA_URLS[oa_key] if oa_key else None,
                        "license": None,
                    },
                )
            render.SITE = tmp / f"site-{n}"
            bad += check(render.main() == 0, f"synthetic render {n} failed")

            for wid, (doi_key, oa_key) in scenario.items():
                detail = render.SITE / "w" / wid / "index.html"
                page = detail.read_text(encoding="utf-8") if detail.exists() else ""
                panel = links_panel(page)
                bad += check(bool(panel), f"{wid} has no Links panel in render {n}")

                csl_links = re.findall(
                    r'<a href="([^"]+)" download>Download CSL-JSON</a>', page,
                )
                bad += check(
                    len(csl_links) == 1,
                    f"{wid} does not have exactly one CSL-JSON download link "
                    f"in render {n}: {csl_links}",
                )
                if len(csl_links) == 1:
                    href = csl_links[0]
                    bad += check(href == "citation.csl.json",
                                 f"{wid} CSL-JSON link href is {href!r}")
                    target = (detail.parent / href).resolve()
                    bad += check(
                        target == (render.SITE / "w" / wid / "citation.csl.json").resolve()
                        and target.exists(),
                        f"{wid} CSL-JSON link does not resolve to its static artifact",
                    )

                doi = DOIS[doi_key] if doi_key else None
                oa_url = OA_URLS[oa_key] if oa_key else None
                bad += check(
                    panel.split(" &middot; ") == expected_links(doi, oa_url, wid),
                    f"{wid} Links panel in render {n} is {panel!r}",
                )
                bad += check(
                    (f'<a href="{doi}">DOI</a>' in panel) if doi
                    else ("<a href=\"https://doi.org/" not in panel),
                    f"{wid} DOI link does not follow the work's DOI in render {n}",
                )
                bad += check(
                    (f'<a href="{oa_url}">Open access copy</a>' in panel) if oa_url
                    else ("Open access copy" not in panel),
                    f"{wid} open-access link does not follow the work's OA URL "
                    f"in render {n}",
                )
    finally:
        (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
         render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_csl_json_link_presence:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
