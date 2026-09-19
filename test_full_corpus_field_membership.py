#!/usr/bin/env python3
"""Every committed work page must resolve its field-membership links.

test_full_corpus_render.py already proves every anchor on the rendered site
resolves somewhere; this test proves the narrower, work-page-specific claim
that motivated t1: each of the 3,000 committed works gets exactly one Fields
section, and the set of field keys those sections point at is exactly the
set of fields/<key>/index.html directories the same build emitted.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import posixpath
import re
import shutil
import sys
import tempfile
from pathlib import Path

import render


ROOT = Path(__file__).parent
DATA = ROOT / "web" / "data"
ASSETS = ROOT / "web" / "assets"

SECTION_RE = re.compile(
    r'<section class="field-memberships" aria-labelledby="field-memberships-heading">(.*?)</section>',
    re.S,
)
HREF_RE = re.compile(r'<a href="([^"]+)">')


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


def field_key_from_href(source_route: str, href: str) -> str:
    """Resolve a membership link to a field key, or raise if it isn't one."""
    resolved = posixpath.normpath(posixpath.join(source_route, href))
    parts = resolved.strip("/").split("/")
    if len(parts) != 2 or parts[0] != "fields":
        raise AssertionError(f"{source_route} -> {href!r}: not a fields/<key>/ link")
    return parts[1]


def built_field_keys(site: Path) -> set[str]:
    fields_dir = site / "fields"
    return {
        child.name
        for child in fields_dir.iterdir()
        if child.is_dir() and (child / "index.html").is_file()
    }


def main() -> int:
    try:
        with rendered_site() as site:
            expected_count = len(json.loads((DATA / "works-index.json").read_text()))

            work_dirs = sorted(p for p in (site / "w").iterdir() if p.is_dir())
            pages = {p.name: (p / "index.html") for p in work_dirs if (p / "index.html").is_file()}
            if len(pages) != expected_count:
                raise AssertionError(
                    f"rendered {len(pages)} work pages, works-index.json declares {expected_count}"
                )

            build_keys = built_field_keys(site)
            linked_keys: set[str] = set()
            for wid, page_path in pages.items():
                page = page_path.read_text(encoding="utf-8")
                source_route = f"/w/{wid}/"

                sections = SECTION_RE.findall(page)
                if len(sections) != 1:
                    raise AssertionError(
                        f"{source_route}: expected exactly one field-memberships section, found {len(sections)}"
                    )

                hrefs = HREF_RE.findall(sections[0])
                if not hrefs:
                    raise AssertionError(f"{source_route}: field-memberships section has no links")

                for href in hrefs:
                    key = field_key_from_href(source_route, href)
                    if key not in build_keys:
                        raise AssertionError(
                            f"{source_route} -> {href!r}: fields/{key}/index.html was not emitted by this build"
                        )
                    linked_keys.add(key)

            if linked_keys != build_keys:
                missing = sorted(build_keys - linked_keys)
                extra = sorted(linked_keys - build_keys)
                raise AssertionError(
                    f"linked field keys differ from the build's field directory; "
                    f"unlinked={missing}, unexpected={extra}"
                )

            print(f"test_full_corpus_field_membership: {len(pages)} work pages audited")
    except AssertionError as error:
        print(f"test_full_corpus_field_membership: FAILED: {error}")
        return 1

    print("test_full_corpus_field_membership: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
