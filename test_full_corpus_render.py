#!/usr/bin/env python3
"""Render the committed corpus and verify every emitted route and anchor."""
from __future__ import annotations

from contextlib import contextmanager
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import posixpath
import shutil
import sys
import tempfile
from urllib.parse import unquote, urlsplit

import render
import corpus_contract


ROOT = Path(__file__).parent
DATA = ROOT / "web" / "data"
ASSETS = ROOT / "web" / "assets"
FIXED_HTML_ROUTES = {
    "index.html",
    "works/index.html",
    "authors/index.html",
    "authors/low-confidence/index.html",
    "works/partial/index.html",
    "works/suspect/index.html",
    "works/missing-title/index.html",
    "works/missing-authors/index.html",
    "works/doi-year-mismatch/index.html",
    "works/no-references/index.html",
    "works/doi-year-disagreement/index.html",
    "works/heavily-cited-no-references/index.html",
    "works/title-disagreement/crossref/index.html",
    "works/title-disagreement/europepmc/index.html",
    "works/venue-disagreement/crossref/index.html",
    "works/venue-disagreement/europepmc/index.html",
    "works/date-disagreement/crossref/index.html",
    "works/date-disagreement/europepmc/index.html",
    "institutions/index.html",
    "topics/index.html",
    "methodology/index.html",
    "fields/index.html",
}
DETAIL_ROUTES = {
    "works": "w",
    "authors": "a",
    "institutions": "i",
    "topics": "t",
}


@contextmanager
def rendered_site():
    """Render repository inputs into a disposable site and restore render globals."""
    saved = render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS
    temporary = Path(tempfile.mkdtemp())
    try:
        render.DATA = DATA
        render.SITE = temporary / "site"
        render.ASSETS = ASSETS
        if render.main() != 0:
            raise AssertionError("render.main() failed for the committed corpus")
        yield render.SITE
    finally:
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(temporary, ignore_errors=True)


class PageLinks(HTMLParser):
    """Collect href destinations and HTML named fragments without a browser."""
    def __init__(self):
        super().__init__()
        self.hrefs = []
        self.fragments = set()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "href" in attributes:
            self.hrefs.append(attributes["href"])
        for name in ("id", "name"):
            if attributes.get(name):
                self.fragments.add(attributes[name])


def parse_page(page: Path) -> tuple[list[str], set[str]]:
    parsed = PageLinks()
    parsed.feed(page.read_text(encoding="utf-8"))
    parsed.close()
    return parsed.hrefs, parsed.fragments


def load_index(name: str) -> list[dict]:
    path = DATA / name
    return json.loads(path.read_text()) if path.exists() else []


def expected_html_routes() -> set[str]:
    routes = set(FIXED_HTML_ROUTES)
    field_index = DATA / "fields-index.json"
    if field_index.exists():
        field_keys = [field["key"] for field in load_index("fields-index.json")]
    else:
        corpus = json.loads((DATA / "corpus.json").read_text())
        field_keys = corpus_contract.normalize(corpus["definition"])
    routes.update(f"fields/{key}/index.html" for key in field_keys)
    for index_name, route_prefix in DETAIL_ROUTES.items():
        for row in load_index(f"{index_name}-index.json"):
            routes.add(f"{route_prefix}/{row['id']}/index.html")
    return routes


def route_for(path: Path, site: Path) -> str:
    relative = path.relative_to(site).as_posix()
    return "/" if relative == "index.html" else f"/{relative[:-len('index.html')]}"


@lru_cache
def local_target(site: Path, requested: str) -> tuple[Path | None, str | None]:
    """Resolve one output path once; most links share one of few destinations."""
    candidate = Path(os.path.normpath(site / requested.lstrip("/")))
    try:
        candidate.relative_to(site)
    except ValueError:
        return None, "path escapes the rendered site"

    if candidate.is_dir():
        candidate /= "index.html"
        if not candidate.is_file():
            return None, "directory index is missing"
    elif not candidate.is_file():
        return None, "target file is missing"
    return candidate, None


def target_path(site: Path, source_route: str, href: str) -> tuple[Path, str] | None:
    """Return a local anchor target, or None for a genuinely external URL."""
    resolved = urlsplit(href)
    origin = urlsplit(render.SITE_URL)

    if resolved.scheme or resolved.netloc:
        if resolved.netloc != origin.netloc or resolved.scheme not in ("", origin.scheme):
            return None

    requested = unquote(resolved.path)
    if not requested:
        requested = "/" if resolved.netloc else source_route
    elif not requested.startswith("/"):
        requested = posixpath.normpath(posixpath.join(source_route, requested))
    candidate, error = local_target(site, requested)
    if error:
        raise AssertionError(f"{source_route} -> {href!r}: {error}")
    return candidate, unquote(resolved.fragment)


def audit_anchors(site: Path) -> list[str]:
    page_paths = list(site.rglob("*.html"))
    workers = min(4, os.cpu_count() or 1)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        pages = dict(zip(page_paths, executor.map(parse_page, page_paths, chunksize=32)))

    failures = []
    for source, (hrefs, _) in pages.items():
        source_route = route_for(source, site)
        for href in hrefs:
            try:
                target = target_path(site, source_route, href)
            except AssertionError as error:
                failures.append(str(error))
                continue
            if target is None:
                continue
            target_page, fragment = target
            if fragment:
                if target_page.suffix != ".html":
                    failures.append(
                        f"{route_for(source, site)} -> {href!r}: fragment target is not HTML"
                    )
                elif fragment not in pages[target_page][1]:
                    failures.append(
                        f"{route_for(source, site)} -> {href!r}: fragment #{fragment!r} is missing"
                    )
    return failures


def main() -> int:
    try:
        with rendered_site() as site:
            actual = {path.relative_to(site).as_posix() for path in site.rglob("*.html")}
            expected = expected_html_routes()
            if actual != expected:
                missing = sorted(expected - actual)
                unexpected = sorted(actual - expected)
                raise AssertionError(
                    f"HTML route set differs; missing={missing[:8]}, unexpected={unexpected[:8]}"
                )

            failures = audit_anchors(site)
            if failures:
                raise AssertionError("broken internal anchors:\n  " + "\n  ".join(failures[:20]))
    except AssertionError as error:
        print(f"test_full_corpus_render: FAILED: {error}")
        return 1

    print("test_full_corpus_render: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
