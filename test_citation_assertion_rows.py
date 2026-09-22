#!/usr/bin/env python3
"""`render.citation_assertion_rows` renders one row per exported citation
assertion, in the order the edge carried them.

Each row must show the human-readable `CITATION_SOURCE_NAMES` label -- or the
escaped source id itself when the id is not one of the known citation sources
-- the complete sha256 hash (via the existing `payload_source_link` helper,
so invalid or absent URLs stay non-clickable without hiding the hash), and the
payload's exported `fetched_at`. An empty (or legacy/missing) assertion list
must render nothing invented.
"""
from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import render

ROOT = Path(__file__).parent
COMMITTED = (ROOT / "web" / "data", ROOT / "web" / "site")

A, B, C, D, UNRESOLVED = (char * 64 for char in "abcde")

SOURCE_URLS = {
    A: "https://api.openalex.org/works/W1",
    B: "https://api.crossref.org/works/10.1/x",
    C: "https://europepmc.org/article/MED/1",
}
FETCHED = {
    A: "2026-09-01T01:02:03+00:00",
    B: "2026-09-02T04:05:06+00:00",
    C: "2026-09-03T07:08:09+00:00",
    D: "2026-09-04T10:11:12+00:00",
}
PAYLOADS = {sha: {"url": url, "fetched_at": FETCHED[sha]} for sha, url in SOURCE_URLS.items()}
# A stored URL that fails validation: the hash must still show, unlinked.
PAYLOADS[D] = {"url": "javascript:alert(1)", "fetched_at": FETCHED[D]}
# UNRESOLVED never made it into the payload map at all.

ASSERTIONS = [
    {"source": "openalex", "raw": A},
    {"source": "crossref", "raw": B},
    # An id this build doesn't know the label for -- and one carrying HTML
    # metacharacters, so the escaping has to survive the fallback path too.
    {"source": "new-index<script>", "raw": C},
    {"source": "europepmc", "raw": D},
    {"source": "arxiv", "raw": UNRESOLVED},
]

HASH = re.compile(r"sha256 ([0-9a-f]{64})")


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


class AssertionRows(HTMLParser):
    """The visible text and anchors of every `<li>` in the rendered list."""

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


def parse(document: str) -> tuple[int, list[dict]]:
    parser = AssertionRows()
    parser.feed(document)
    parser.close()
    return parser.lists, parser.rows


def visible_hash(text: str) -> str | None:
    match = HASH.search(text)
    return match.group(1) if match else None


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

    document = render.citation_assertion_rows(ASSERTIONS, PAYLOADS)

    # No raw, unescaped HTML metacharacter from the unknown source id leaked
    # into the markup -- checked before the parser gets anywhere near it,
    # since an HTMLParser would otherwise just treat it as a real tag.
    bad += check("<script>" not in document,
                 "an unrecognised source id was not escaped before being rendered")
    bad += check("new-index&lt;script&gt;" in document,
                 "the escaped fallback label for an unknown source id is missing")

    lists, rows = parse(document)
    bad += check(lists == 1, f"rendered {lists} provenance lists, expected exactly one")
    bad += check(len(rows) == len(ASSERTIONS),
                 f"rendered {len(rows)} rows for {len(ASSERTIONS)} assertions -- not one row each")

    expected_labels = [
        "OpenAlex", "Crossref", "new-index<script>", "Europe PMC", "arXiv",
    ]
    expected_hashes = [A, B, C, D, UNRESOLVED]
    for row, label, sha in zip(rows, expected_labels, expected_hashes):
        bad += check(label in row["text"],
                     f"row {row['text']!r} is missing its source label {label!r}")
        bad += check(visible_hash(row["text"]) == sha,
                     f"row {row['text']!r} did not show the complete hash {sha}")
        bad += check(f"fetched {FETCHED.get(sha, 'unknown')}" in row["text"],
                     f"row {row['text']!r} lost its exported fetch time")

    # Exactly one followable anchor for A, B and C, whose stored URLs are valid.
    for row, sha in zip(rows[:3], (A, B, C)):
        url = SOURCE_URLS[sha]
        anchors = row["anchors"]
        bad += check(
            len(anchors) == 1 and anchors[0]["href"] == url and anchors[0]["text"],
            f"row for {sha} carries anchors {anchors}, not exactly one link to {url}",
        )

    # D's stored URL fails validation and UNRESOLVED has none at all -- the
    # hash must still be visible (checked above) but never turned into a link.
    for row, sha in zip(rows[3:], (D, UNRESOLVED)):
        bad += check(row["anchors"] == [],
                     f"row for {sha} invented a link for an invalid or absent source URL")

    # Rows preserve exported order, duplicates and all -- not sorted or deduped
    # like the aggregate provenance list, since each assertion is its own claim.
    reordered = [ASSERTIONS[1], ASSERTIONS[0], ASSERTIONS[0]]
    reordered_hashes = [visible_hash(r["text"]) for r in parse(
        render.citation_assertion_rows(reordered, PAYLOADS))[1]]
    bad += check(reordered_hashes == [B, A, A],
                 f"assertion rows {reordered_hashes} were not rendered in exported order")

    # An empty or legacy (missing) assertion list invents nothing.
    bad += check(render.citation_assertion_rows([], PAYLOADS) == "",
                 "an empty assertion list produced fabricated provenance")
    bad += check(render.citation_assertion_rows(None, PAYLOADS) == "",
                 "a legacy edge with no assertions field produced fabricated provenance")

    for directory in COMMITTED:
        bad += check(tree_state(directory) == before[directory],
                     f"the test modified committed data under {directory.relative_to(ROOT)}")

    print("test_citation_assertion_rows:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
