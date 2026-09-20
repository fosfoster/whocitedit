#!/usr/bin/env python3
"""Offline coverage for the CSL-JSON download link on rendered work pages."""
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
        render.DATA = data
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "synthetic render failed")

        for path in data.glob("works/*.json"):
            payload = json.loads(path.read_text())
            for wid in payload:
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
                    bad += check(href == "citation.csl.json",
                                 f"{wid} CSL-JSON link is not relative")
                    target = (detail.parent / href).resolve()
                    expected = (render.SITE / "w" / wid / "citation.csl.json").resolve()
                    bad += check(target == expected and target.exists(),
                                 f"{wid} CSL-JSON link does not resolve to its static citation file")
    finally:
        (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
         render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_csl_json_link_added:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
