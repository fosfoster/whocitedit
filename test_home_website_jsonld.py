#!/usr/bin/env python3
"""Offline coverage for the homepage WebSite JSON-LD block."""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import render
from test_cohort_pages import write_fixture


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def extract_json_ld(block: str):
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', block, re.S)
    return json.loads(match.group(1)) if match else None


def main() -> int:
    bad = 0

    direct = render.home_head_metadata(render.canonical_url(""))
    ld = extract_json_ld(direct)
    bad += check(ld is not None, "home_head_metadata did not emit a ld+json block")
    if ld:
        bad += check(ld.get("@type") == "WebSite", "@type is not WebSite")
        bad += check(ld.get("@id") == render.SITE_URL, "@id does not equal render.SITE_URL")
        bad += check(ld.get("url") == render.SITE_URL, "url does not equal render.SITE_URL")
        bad += check(ld.get("name") == render.SITE_NAME, "name does not equal render.SITE_NAME")
        bad += check(bool(ld.get("description")), "description is empty")

    tmp = Path(tempfile.mkdtemp())
    saved = (render.DATA, render.SITE, render.ASSETS)
    try:
        data = tmp / "data"
        write_fixture(data)
        render.DATA = data
        render.SITE = tmp / "site"
        render.ASSETS = Path(__file__).parent / "web" / "assets"
        bad += check(render.main() == 0, "synthetic render failed")

        home = (render.SITE / "index.html").read_text()
        rendered_ld = extract_json_ld(home)
        bad += check(rendered_ld is not None,
                     "index.html has no application/ld+json block")
        if rendered_ld:
            bad += check(rendered_ld.get("@type") == "WebSite",
                         "rendered @type is not WebSite")
            bad += check(rendered_ld.get("@id") == render.SITE_URL,
                         "rendered @id does not equal render.SITE_URL")
            bad += check(rendered_ld.get("url") == render.SITE_URL,
                         "rendered url does not equal render.SITE_URL")
            bad += check(rendered_ld.get("name") == render.SITE_NAME,
                         "rendered name does not equal render.SITE_NAME")
            bad += check(bool(rendered_ld.get("description")),
                         "rendered description is empty")
    finally:
        render.DATA, render.SITE, render.ASSETS = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_home_website_jsonld:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
