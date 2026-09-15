#!/usr/bin/env python3
"""Offline coverage for RIS download links on rendered work pages."""
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
        update_work(data, "W1", doi="https://doi.org/10.1000/with-doi")
        update_work(data, "W2", doi=None)
        update_work(data, "W3", doi="https://doi.org/10.1000/another-doi")

        render.DATA = data
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "synthetic render failed")

        for wid in ("W1", "W2", "W3"):
            detail = render.SITE / "w" / wid / "index.html"
            page = detail.read_text(encoding="utf-8") if detail.exists() else ""
            panel = links_panel(page)
            bad += check(bool(panel), f"{wid} has no Links panel")
            ris_links = re.findall(
                r'<a href="([^"]+)" download>Download RIS</a>', panel,
            )
            bad += check(len(ris_links) == 1,
                         f"{wid} does not have exactly one RIS download link")
            if len(ris_links) == 1:
                href = ris_links[0]
                bad += check(href == "citation.ris", f"{wid} RIS link is not relative")
                target = (detail.parent / href).resolve()
                expected = (render.SITE / "w" / wid / "citation.ris").resolve()
                bad += check(target == expected and target.exists(),
                             f"{wid} RIS link does not resolve to its static citation file")

        w2_panel = links_panel((render.SITE / "w" / "W2" / "index.html").read_text())
        bad += check(
            '<a href="https://doi.org/' not in w2_panel,
            "work without a DOI emitted a DOI link",
        )
        bad += check(
            '<a href="citation.ris" download>Download RIS</a>' in w2_panel,
            "work without a DOI is missing its RIS download link",
        )
    finally:
        (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
         render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_ris_link:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
