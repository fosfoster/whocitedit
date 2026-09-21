#!/usr/bin/env python3
"""Offline coverage for the homepage's advertised global search."""
import json
import re
import shutil
import sys
import tempfile
from html.parser import HTMLParser
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


class GlobalSearchFormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "form" and "data-global-search" in attributes:
            self.forms.append(attributes)


def check_search_action(ld: dict | None, label: str) -> int:
    bad = 0
    action = ld.get("potentialAction") if ld else None
    bad += check(isinstance(action, dict), f"{label} WebSite has no potentialAction")
    if not isinstance(action, dict):
        return bad
    bad += check(action.get("@type") == "SearchAction",
                 f"{label} potentialAction is not SearchAction")
    target = action.get("target")
    bad += check(isinstance(target, dict), f"{label} SearchAction has no EntryPoint target")
    if isinstance(target, dict):
        template = target.get("urlTemplate", "")
        bad += check(target.get("@type") == "EntryPoint",
                     f"{label} SearchAction target is not EntryPoint")
        expected_template = f"{render.SITE_URL}/?q={{search_term_string}}"
        bad += check(template == expected_template,
                     f"{label} urlTemplate is not the global search URL")
    bad += check(action.get("query-input") == "required name=search_term_string",
                 f"{label} SearchAction has the wrong query-input")
    return bad


def main() -> int:
    bad = 0

    direct = extract_json_ld(render.home_head_metadata(render.canonical_url("")))
    bad += check(direct is not None, "home_head_metadata did not emit ld+json")
    bad += check_search_action(direct, "helper")

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
        rendered = extract_json_ld(home)
        bad += check(rendered is not None, "index.html has no application/ld+json block")
        bad += check_search_action(rendered, "rendered")

        parser = GlobalSearchFormParser()
        parser.feed(home)
        bad += check(len(parser.forms) == 1, "index.html has no data-global-search form")
        if parser.forms:
            bad += check("data/search-index.json" in parser.forms[0].get("data-index", ""),
                         "global search form does not point to data/search-index.json")
    finally:
        render.DATA, render.SITE, render.ASSETS = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_home_search_action:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
