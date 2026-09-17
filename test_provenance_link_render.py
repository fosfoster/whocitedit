#!/usr/bin/env python3
"""Sorted, deduplicated provenance rows keep their hash, fetch time and source link.

An aggregate resolves to the payloads behind it in whatever order and with
whatever repetition its sources produced; the reader sees one row per distinct
payload, in hash order, on every page type that embeds the shared rows. This
gate renders those rows from in-memory fixtures shaped like `payloads.json` and
reads them back through an HTML parser: a row whose payload carries a valid
exported source URL holds exactly one anchor, its href is that URL character
for character, and neither the complete hash nor the exported fetch time is
dropped to make room for the link. Nothing under `web/data/` or `web/site/` is
written, and the gate checks that it was not.
"""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import render

ROOT = Path(__file__).parent
COMMITTED = (ROOT / "web" / "data", ROOT / "web" / "site")

A, B, C, D, UNRESOLVED, UNFOLLOWABLE = (char * 64 for char in "abcdef")

# Payloads a reader can follow: each of these rows carries exactly one anchor,
# and its href is this URL. B has the exported shape, a 50-id OR-filter carrying
# percent escapes and query separators, the characters an href attribute has to
# hand back unchanged.
SOURCE_URLS = {
    A: "https://api.openalex.org/works/W1",
    B: "https://api.openalex.org/authors?filter=openalex_id%3AA1%7CA2"
       "&select=id%2Corcid&per-page=50&mailto=reader%40example.org",
    C: "https://api.openalex.org/works?filter=openalex:W2|W3",
}
FETCHED = {
    A: "2026-09-01T01:02:03+00:00",
    B: "2026-09-02T04:05:06+00:00",
    C: "2026-09-03T07:08:09+00:00",
    D: "2026-09-04T10:11:12+00:00",
    UNFOLLOWABLE: "2026-09-06T16:17:18+00:00",
}
PAYLOADS = {sha: {"url": url, "fetched_at": FETCHED[sha]} for sha, url in SOURCE_URLS.items()}
# A release that stored the fetch time before it learned the URL.
PAYLOADS[D] = {"fetched_at": FETCHED[D]}
# A value nobody can follow is not a source link, however it got exported.
PAYLOADS[UNFOLLOWABLE] = {"url": "javascript:alert(1)", "fetched_at": FETCHED[UNFOLLOWABLE]}
# UNRESOLVED is named by an entity and absent from the payload map altogether.

HASH = re.compile(r"sha256 ([0-9a-f]{64})")


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


class ProvenanceRows(HTMLParser):
    """The visible text and the anchors of every row inside a provenance list."""

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


def visible_hash(text: str) -> str | None:
    match = HASH.search(text)
    return match.group(1) if match else None


def check_rows(document: str, resolved: list[str], context: str) -> int:
    """Every criterion of the ticket, against one rendered provenance list.

    `resolved` is what the entity resolves to, in export order and with its
    repetition; the rows must be its sorted, deduplicated rendering.
    """
    lists, rows = provenance_rows(document)
    bad = check(lists == 1, f"{context}: rendered {lists} provenance lists, expected exactly one")
    shown = [visible_hash(row["text"]) for row in rows]
    bad += check(
        shown == sorted(set(resolved)),
        f"{context}: visible hashes {shown} are not the sorted, deduplicated "
        f"rendering of {resolved}",
    )
    for row, sha in zip(rows, shown):
        if sha is None:
            continue
        bad += check(f"fetched {FETCHED.get(sha, 'unknown')}" in row["text"],
                     f"{context}: row {row['text']!r} lost its exported fetch time")
        anchors = row["anchors"]
        url = SOURCE_URLS.get(sha)
        if url:
            bad += check(
                len(anchors) == 1 and anchors[0]["href"] == url and anchors[0]["text"],
                f"{context}: row for {sha} carries anchors {anchors}, not exactly one "
                f"followable anchor to {url}",
            )
        else:
            bad += check(anchors == [],
                         f"{context}: row for {sha} invented anchors {anchors} "
                         "for a payload with no valid exported source URL")
    return bad


def work(raw) -> dict:
    return {
        "id": "W1", "title": "Work", "year": 2024, "date": None, "doi": None,
        "source": {"id": None, "name": None}, "oa": {"url": None, "license": None},
        "abstract": {"text": None, "reason": None}, "cited_by_count": 0,
        "in_corpus_cited_by": 0, "authors": [], "topics": [],
        "graph": {"nodes": [], "shown": 0, "available": 0},
        "quality": {"band": "complete", "sentence": "Complete", "evidence": []},
        "raw": raw, "openalex_url": "https://openalex.org/W1",
    }


def author(raw, works: list[str]) -> dict:
    return {
        "id": "A1", "name": "Ada Lovelace", "orcid": None,
        "openalex_url": "https://openalex.org/A1",
        "confidence": {"band": "high", "evidence": []},
        "in_corpus": {"works": len(works), "hindex": 1},
        "cited_by_count": 0, "works_count": len(works),
        "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
        "works": [{"id": wid, "title": wid, "position": None, "year": 2024, "cited": 0}
                  for wid in works],
        "institutions": [], "raw": raw,
    }


def tree_state(directory: Path) -> dict[str, tuple[int, int]]:
    if not directory.is_dir():
        return {}
    return {
        str(path.relative_to(ROOT)): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in directory.rglob("*")
        if path.is_file()
    }


def main() -> int:
    bad = 0
    before = {directory: tree_state(directory) for directory in COMMITTED}
    bands = {"high": "High confidence"}

    # The shared rows themselves: list and scalar hash forms, then the rows that
    # resolve to no followable source and must say so without a link.
    surfaces = [
        ("provenance_html list", render.provenance_html([C, A, B, A, C], PAYLOADS), [C, A, B, A, C]),
        ("provenance_html scalar", render.provenance_html(B, PAYLOADS), [B]),
        ("provenance_html unlinked",
         render.provenance_html([UNFOLLOWABLE, UNRESOLVED, D, UNRESOLVED], PAYLOADS),
         [UNFOLLOWABLE, UNRESOLVED, D, UNRESOLVED]),
    ]

    # Every page type that embeds the rows. The fallback author is the one whose
    # provenance is resolved rather than stored: three linked works naming
    # overlapping payloads in export order, read back as one sorted list.
    work_raw = {"W1": [C, A], "W2": A, "W3": [B, C]}
    linked = [C, A, A, B, C]
    fallback = author(None, list(work_raw))
    bad += check(
        render.author_provenance(fallback, work_raw) == ([A, B, C], True),
        f"author provenance did not resolve {linked} through linked works to [A, B, C]",
    )
    surfaces += [
        ("work page", render.render_work(work([C, A, C]), {}, {}, PAYLOADS, {}, set()), [C, A, C]),
        ("fallback author page",
         render.render_author(fallback, {}, bands, PAYLOADS, set(), work_raw), linked),
        ("direct author page",
         render.render_author(author([B, B], ["W1"]), {}, bands, PAYLOADS, set(), work_raw), [B, B]),
        ("institution page",
         render.render_institution({"id": "I1", "name": "Institution", "raw": [B, A, B]},
                                   PAYLOADS, set(), set()), [B, A, B]),
        ("topic page",
         render.render_topic({"id": "T1", "name": "Topic", "raw": [A, UNRESOLVED, A]},
                             PAYLOADS, set(), set()), [A, UNRESOLVED, A]),
    ]
    for context, document, resolved in surfaces:
        bad += check_rows(document, resolved, context)

    for directory in COMMITTED:
        bad += check(tree_state(directory) == before[directory],
                     f"the test modified committed data under {directory.relative_to(ROOT)}")

    print("test_provenance_link_render:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
