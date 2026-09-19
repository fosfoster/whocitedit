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


def load_work(data: Path, wid: str) -> dict:
    for path in (data / "works").glob("*.json"):
        payload = json.loads(path.read_text())
        if wid in payload:
            return payload[wid]
    raise KeyError(wid)


def links_panel(page: str) -> str:
    match = re.search(r"<h2>Links</h2>\s*<p>(.*?)</p>", page, re.DOTALL)
    return match.group(1) if match else ""


def download_links(panel: str, label: str) -> list:
    return re.findall(rf'<a href="([^"]+)" download>Download {label}</a>', panel)


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

        details = sorted((render.SITE / "w").glob("*/index.html"))
        bad += check({d.parent.name for d in details} == {"W1", "W2", "W3"},
                     "rendered work pages do not cover the synthetic corpus")

        for detail in details:
            wid = detail.parent.name
            work = load_work(data, wid)
            page = detail.read_text(encoding="utf-8")
            panel = links_panel(page)
            bad += check(bool(panel), f"{wid} has no Links panel")

            csl_links = download_links(panel, "CSL-JSON")
            bad += check(len(csl_links) == 1,
                         f"{wid} does not have exactly one CSL-JSON download link")
            if len(csl_links) == 1:
                href = csl_links[0]
                bad += check(not href.startswith(("/", "http", "..")),
                             f"{wid} CSL-JSON link is not relative to its own page")
                target = (detail.parent / href).resolve()
                bad += check(target.parent == detail.parent.resolve(),
                             f"{wid} CSL-JSON link does not sit beside its page")
                bad += check(target.exists(),
                             f"{wid} CSL-JSON link does not resolve to a static file")
                if target.exists():
                    payload = json.loads(target.read_text(encoding="utf-8"))
                    bad += check(payload.get("id") == wid,
                                 f"{wid} CSL-JSON link target is not that work's CSL-JSON")
                    bad += check(payload == render.work_csl_json(work),
                                 f"{wid} CSL-JSON was not rendered from the exported work")

            for label, artifact in (("BibTeX", "citation.bib"), ("RIS", "citation.ris")):
                found = download_links(panel, label)
                bad += check(len(found) == 1,
                             f"{wid} does not have exactly one {label} download link")
                if len(found) == 1:
                    bad += check(found[0] == artifact,
                                 f"{wid} {label} link is not relative")
                    bad += check((detail.parent / found[0]).exists(),
                                 f"{wid} {label} link does not resolve to its static citation file")

            doi_link = f'<a href="{work["doi"]}">DOI</a>' if work["doi"] else None
            bad += check(
                (doi_link in panel) if doi_link else ('>DOI</a>' not in panel),
                f"{wid} DOI link is not conditional on its DOI",
            )
            oa_link = (f'<a href="{work["oa"]["url"]}">Open access copy</a>'
                       if work["oa"]["url"] else None)
            bad += check(
                (oa_link in panel) if oa_link else ('Open access copy' not in panel),
                f"{wid} open-access link is not conditional on an open-access URL",
            )
            bad += check(f'<a href="https://openalex.org/{wid}">OpenAlex record</a>' in panel,
                         f"{wid} lost its OpenAlex link")

            # The CSL-JSON is a render-time artifact: nothing on the page builds it.
            scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", page, re.DOTALL | re.I)
            bad += check(
                not any(re.search(r"csl|citation\.json", body, re.I) for body in scripts),
                f"{wid} generates CSL-JSON from browser code instead of at render time",
            )
            bad += check(page.count("citation.json") == 1,
                         f"{wid} does not name citation.json exactly once, as its download link")

        for asset in sorted((render.SITE / "assets").glob("*.js")):
            bad += check(
                not re.search(r"csl|citation\.json", asset.read_text(encoding="utf-8"), re.I),
                f"assets/{asset.name} produces CSL-JSON in the browser",
            )
    finally:
        (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
         render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_csl_json_link:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
