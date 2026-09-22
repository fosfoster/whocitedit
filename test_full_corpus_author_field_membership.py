#!/usr/bin/env python3
"""Every committed author page must resolve its field-membership links.

The author membership unit tests cover small synthetic corpora.  This audit
renders the committed export once, then verifies every author page against the
author and work shards rather than renderer state: each page lists precisely
the union of fields belonging to its own works, in field-index order.
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

import corpus_contract
import render


ROOT = Path(__file__).parent
DATA = ROOT / "web" / "data"
ASSETS = ROOT / "web" / "assets"

SECTION_RE = re.compile(
    r'<section class="author-field-memberships" aria-labelledby="author-field-memberships-heading">(.*?)</section>',
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


def load_shards(kind: str) -> dict[str, dict]:
    rows = {}
    for shard in sorted((DATA / kind).glob("*.json")):
        rows.update(json.loads(shard.read_text(encoding="utf-8")))
    return rows


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


def work_field_memberships(works: dict[str, dict]) -> tuple[list[str], dict[str, list[str]]]:
    """Independently reproduce the corpus field-membership contract."""
    exported_index_path = DATA / "fields-index.json"
    exported_index = (
        json.loads(exported_index_path.read_text(encoding="utf-8"))
        if exported_index_path.is_file() else None
    )
    memberships_present = ["fields" in work for work in works.values()]

    if exported_index is None and not any(memberships_present):
        normalized = corpus_contract.normalize(
            json.loads((DATA / "corpus.json").read_text(encoding="utf-8"))["definition"]
        )
        if len(normalized) != 1:
            raise AssertionError("legacy corpus definition must normalize to one field")
        key = next(iter(normalized))
        return [key], {wid: [key] for wid in works}

    if exported_index is None or not all(memberships_present):
        raise AssertionError("incomplete field export: need both fields-index.json and work fields arrays")

    field_order = [field["key"] for field in exported_index]
    return field_order, {wid: work["fields"] for wid, work in works.items()}


def expected_field_keys(
    author: dict,
    work_memberships: dict[str, list[str]],
    field_order: list[str],
) -> list[str]:
    member_fields: set[str] = set()
    for work in author["works"]:
        wid = work["id"]
        if wid not in work_memberships:
            raise AssertionError(f"author {author['id']} references missing work {wid}")
        member_fields.update(work_memberships[wid])

    index_keys = set(field_order)
    unknown_keys = sorted(member_fields - index_keys)
    if unknown_keys:
        raise AssertionError(
            f"author {author['id']} works use fields absent from the field index: {unknown_keys}"
        )
    return [key for key in field_order if key in member_fields]


def main() -> int:
    try:
        with rendered_site() as site:
            authors_index = json.loads((DATA / "authors-index.json").read_text(encoding="utf-8"))
            expected_ids = {author["id"] for author in authors_index}
            if len(expected_ids) != len(authors_index):
                raise AssertionError(
                    f"authors-index.json declares {len(authors_index)} authors but only "
                    f"{len(expected_ids)} distinct ids"
                )

            pages = {
                page.parent.name: page
                for page in sorted((site / "a").glob("*/index.html"))
            }
            missing_ids = sorted(expected_ids - pages.keys())
            unexpected_ids = sorted(pages.keys() - expected_ids)
            if missing_ids or unexpected_ids:
                raise AssertionError(
                    f"rendered author pages do not match authors-index.json "
                    f"({len(pages)} rendered, {len(expected_ids)} declared); "
                    f"missing={missing_ids[:10]}, unexpected={unexpected_ids[:10]}"
                )

            authors = load_shards("authors")
            works = load_shards("works")
            field_order, work_memberships = work_field_memberships(works)
            build_keys = built_field_keys(site)
            linked_keys: set[str] = set()

            for aid, page_path in pages.items():
                if aid not in authors:
                    raise AssertionError(f"{aid}: no author shard record")
                page = page_path.read_text(encoding="utf-8")
                source_route = f"/a/{aid}/"

                sections = SECTION_RE.findall(page)
                if len(sections) != 1:
                    raise AssertionError(
                        f"{source_route}: expected exactly one author-field-memberships section, "
                        f"found {len(sections)}"
                    )

                hrefs = HREF_RE.findall(sections[0])
                if not hrefs:
                    raise AssertionError(
                        f"{source_route}: author-field-memberships section has no links"
                    )

                page_keys = []
                for href in hrefs:
                    key = field_key_from_href(source_route, href)
                    if key not in build_keys:
                        raise AssertionError(
                            f"{source_route} -> {href!r}: fields/{key}/index.html was not emitted by this build"
                        )
                    page_keys.append(key)
                    linked_keys.add(key)

                expected_keys = expected_field_keys(authors[aid], work_memberships, field_order)
                if page_keys != expected_keys:
                    raise AssertionError(
                        f"{source_route}: field keys differ from its works' membership union; "
                        f"rendered={page_keys}, expected={expected_keys}"
                    )

            if linked_keys != build_keys:
                missing = sorted(build_keys - linked_keys)
                extra = sorted(linked_keys - build_keys)
                raise AssertionError(
                    f"linked field keys differ from the build's field directory; "
                    f"unlinked={missing}, unexpected={extra}"
                )

            print(f"test_full_corpus_author_field_membership: {len(pages)} author pages audited")
    except AssertionError as error:
        print(f"test_full_corpus_author_field_membership: FAILED: {error}")
        return 1

    print("test_full_corpus_author_field_membership: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
