#!/usr/bin/env python3
"""Hermetic export-to-render provenance audit across every entity page type.

`test_full_corpus_provenance.py` proves works and authors against the
committed release; `test_provenance_link_render.py` proves the shared row
renderer against hand-built payload dictionaries. Neither walks every
generated work, author, institution *and* topic page from one export, so a
mistake specific to institution/topic aggregation, or to the fallback path an
author with no direct payload takes through its linked works, could pass both.

This gate builds `test_entity_export`'s synthetic corpus, gives its payloads
safe HTTPS source URLs (the fixture normally uses `file://` URLs, which the
renderer correctly refuses to link), forces one author down the linked-work
fallback while the rest keep direct provenance, exports and renders it to a
temporary site, and for every indexed work/author/institution/topic parses the
rendered provenance rows back out. Each row must resolve to a real payload in
`payloads.json`, and the set of rows on a page -- no more, no fewer, no
repeats -- must equal the payload hashes the exported record actually names,
each with its anchor, complete hash and fetch time intact. Nothing under
`web/data/` or `web/site/` is read, written, or otherwise touched.
"""
from __future__ import annotations

from contextlib import contextmanager
from html.parser import HTMLParser
import json
import shutil
import sys
import tempfile
from pathlib import Path

import db
import export_json
import render
import test_entity_export

ROOT = Path(__file__).parent
COMMITTED = (ROOT / "web" / "data", ROOT / "web" / "site")
HASH_LENGTH = 64
FALLBACK_AUTHOR = "A02"


class ContractError(AssertionError):
    """The export or its rendered reader view violates the provenance contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def hashes(value) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return set(value)
    require(value is None, "unexpected payload-hash shape")
    return set()


def tree_state(directory: Path) -> dict[str, tuple[int, int]]:
    if not directory.is_dir():
        return {}
    return {
        str(path.relative_to(ROOT)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in directory.rglob("*")
        if path.is_file()
    }


def build_fixture(tmp: Path) -> tuple[Path, set[str]]:
    """The shared synthetic corpus, with HTTPS source URLs and a fallback author.

    `test_entity_export.build_corpus` stores every payload behind a `file://`
    URL, which is deliberately unfollowable -- `render.valid_source_url` links
    only http(s). Rewriting those URLs after the fixture is built, rather than
    inside the shared helper, keeps every other consumer of that fixture
    exercising the "no source URL" path it already covers.
    """
    db_path, expected_payloads, _author_sha = test_entity_export.build_corpus(tmp)
    conn = db.connect(db_path)
    for row in conn.execute("SELECT sha256 FROM raw_payload").fetchall():
        conn.execute(
            "UPDATE raw_payload SET url = ? WHERE sha256 = ?",
            (f"https://harvest.example.org/{row['sha256']}", row["sha256"]),
        )
    # A26 authors in this fixture all resolve a direct payload; nulling one
    # author's own raw_sha (the column is nullable, unlike the NOT NULL
    # work.raw_sha) forces it through author_provenance's linked-work fallback
    # without disturbing the works, affiliations or aggregate institution/topic
    # provenance the rest of the audit checks.
    conn.execute("UPDATE author SET raw_sha = NULL WHERE id = ?", (FALLBACK_AUTHOR,))
    conn.commit()
    conn.close()
    return db_path, expected_payloads


@contextmanager
def exported_and_rendered_site(tmp: Path):
    saved = (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
              render.DATA, render.SITE)
    try:
        db_path, expected_payloads = build_fixture(tmp)
        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = ROOT
        require(export_json.main() == 0, "synthetic export failed")

        render.DATA = tmp / "data"
        render.SITE = tmp / "site"
        require(render.main() == 0, "synthetic render failed")
        yield tmp / "data", tmp / "site", expected_payloads
    finally:
        (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
         render.DATA, render.SITE) = saved


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def indexed_ids(data: Path, kind: str) -> set[str]:
    return {row["id"] for row in read_json(data / f"{kind}-index.json")}


def shard_records(data: Path, kind: str) -> dict[str, dict]:
    records: dict[str, dict] = {}
    for path in sorted((data / kind).glob("*.json")):
        records.update(read_json(path))
    return records


def rendered_ids(site: Path, prefix: str) -> set[str]:
    directory = site / prefix
    require(directory.is_dir(), f"rendered site has no {prefix}/ directory")
    return {page.parent.name for page in directory.glob("*/index.html")}


class ProvenanceRows(HTMLParser):
    """Every row of the shared provenance list: its text and its anchors."""

    def __init__(self) -> None:
        super().__init__()
        self.lists = 0
        self.rows: list[dict] = []
        self._in_list = False
        self._row: dict | None = None
        self._anchor: dict | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if tag == "ul" and "provenance-list" in (attributes.get("class") or "").split():
            self.lists += 1
            self._in_list = True
        elif tag == "li" and self._in_list:
            self._row = {"text": [], "anchors": []}
        elif tag == "a" and self._row is not None:
            self._anchor = {"href": attributes.get("href"), "text": []}
            self._row["anchors"].append(self._anchor)

    def handle_data(self, data: str) -> None:
        if self._row is not None:
            self._row["text"].append(data)
        if self._anchor is not None:
            self._anchor["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._anchor is not None:
            self._anchor["text"] = " ".join("".join(self._anchor["text"]).split())
            self._anchor = None
        elif tag == "li" and self._row is not None:
            self._row["text"] = " ".join("".join(self._row["text"]).split())
            self.rows.append(self._row)
            self._row = None
        elif tag == "ul" and self._in_list:
            self._in_list = False


def provenance_rows(document: str) -> tuple[int, list[dict]]:
    parser = ProvenanceRows()
    parser.feed(document)
    parser.close()
    return parser.lists, parser.rows


def require_page_provenance(page: Path, expected: set[str], payloads: dict, context: str) -> None:
    require(page.is_file(), f"{context} has no rendered page")
    document = page.read_text(encoding="utf-8")
    lists, rows = provenance_rows(document)
    require(lists == 1, f"{context}: rendered {lists} provenance lists, expected exactly one")
    require(len(rows) == len(expected),
            f"{context}: rendered {len(rows)} provenance rows for {len(expected)} expected payloads "
            f"(missing/duplicate/extra rows)")

    seen: set[str] = set()
    for row in rows:
        shas = [sha for sha in expected if f"sha256 {sha}" in row["text"]]
        require(len(shas) == 1,
                f"{context}: row {row['text']!r} does not name exactly one expected payload hash")
        sha = shas[0]
        require(sha not in seen, f"{context}: payload {sha} is rendered more than once")
        seen.add(sha)

        payload = payloads[sha]
        require(f"fetched {payload['fetched_at']}" in row["text"],
                f"{context}: row for {sha} lost its exact fetch time")

        anchors = row["anchors"]
        require(len(anchors) == 1 and anchors[0]["text"],
                f"{context}: row for {sha} carries {len(anchors)} anchors, expected exactly one")
        require(anchors[0]["href"] == payload["url"],
                f"{context}: row for {sha} links {anchors[0]['href']!r}, "
                f"not the exported source URL {payload['url']!r}")
    require(seen == expected, f"{context}: rendered rows do not match expected payloads exactly")


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    before = {directory: tree_state(directory) for directory in COMMITTED}
    try:
        with exported_and_rendered_site(tmp) as (data, site, expected_payloads):
            payloads = read_json(data / "payloads.json")
            require(isinstance(payloads, dict) and payloads,
                    "synthetic export produced no payload map")
            require(set(payloads) == expected_payloads,
                    "synthetic export lost or gained a fixture payload")
            require(all(payload.get("url", "").startswith("https://") for payload in payloads.values()),
                    "fixture did not carry safe HTTPS source URLs")

            work_ids = indexed_ids(data, "works")
            author_ids = indexed_ids(data, "authors")
            institution_ids = indexed_ids(data, "institutions")
            topic_ids = indexed_ids(data, "topics")

            works = shard_records(data, "works")
            authors = shard_records(data, "authors")
            institutions = shard_records(data, "institutions")
            topics = shard_records(data, "topics")
            require({*works} == work_ids, "work shards disagree with the work index")
            require({*authors} == author_ids, "author shards disagree with the author index")
            require({*institutions} == institution_ids,
                    "institution shards disagree with the institution index")
            require({*topics} == topic_ids, "topic shards disagree with the topic index")

            work_raw = {wid: work.get("raw") for wid, work in works.items()}
            work_hashes = {wid: hashes(raw) for wid, raw in work_raw.items()}
            require(all(work_hashes.values()), "a synthetic work exported with no payload hash")

            author_hashes: dict[str, set[str]] = {}
            direct_authors, fallback_authors = set(), set()
            for aid, author in authors.items():
                resolved, used_fallback = render.author_provenance(author, work_raw)
                author_hashes[aid] = hashes(resolved)
                require(author_hashes[aid], f"author {aid} resolved to no provenance at all")
                (fallback_authors if used_fallback else direct_authors).add(aid)
            require(FALLBACK_AUTHOR in fallback_authors,
                    f"fixture author {FALLBACK_AUTHOR} did not take the linked-work fallback path")
            require(direct_authors,
                    "fixture lost every author with direct provenance -- only the fallback path ran")

            institution_hashes = {iid: hashes(inst.get("raw")) for iid, inst in institutions.items()}
            topic_hashes = {tid: hashes(topic.get("raw")) for tid, topic in topics.items()}
            require(all(institution_hashes.values()), "a synthetic institution exported with no payload hash")
            require(all(topic_hashes.values()), "a synthetic topic exported with no payload hash")

            require(rendered_ids(site, "w") == work_ids, "rendered work pages differ from the work index")
            require(rendered_ids(site, "a") == author_ids, "rendered author pages differ from the author index")
            require(rendered_ids(site, "i") == institution_ids,
                    "rendered institution pages differ from the institution index")
            require(rendered_ids(site, "t") == topic_ids, "rendered topic pages differ from the topic index")

            for wid, expected in work_hashes.items():
                require_page_provenance(site / "w" / wid / "index.html", expected, payloads, f"work {wid}")
            for aid, expected in author_hashes.items():
                require_page_provenance(site / "a" / aid / "index.html", expected, payloads, f"author {aid}")
            for iid, expected in institution_hashes.items():
                require_page_provenance(site / "i" / iid / "index.html", expected, payloads,
                                         f"institution {iid}")
            for tid, expected in topic_hashes.items():
                require_page_provenance(site / "t" / tid / "index.html", expected, payloads, f"topic {tid}")

            total_pages = len(work_ids) + len(author_ids) + len(institution_ids) + len(topic_ids)

        for directory in COMMITTED:
            require(tree_state(directory) == before[directory],
                    f"the test modified committed data under {directory.relative_to(ROOT)}")
    except ContractError as error:
        print(f"test_entity_provenance_links: FAILED: {error}")
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"test_entity_provenance_links: ok (pages={total_pages}, payloads={len(payloads)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
