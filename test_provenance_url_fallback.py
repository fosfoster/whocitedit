#!/usr/bin/env python3
"""An invalid or absent provenance source URL is shown as text, never as a link."""
import sys
from html.parser import HTMLParser

import render

SHA = "a" * 64
FETCHED_AT = "2026-09-15T12:00:00+00:00"
# What a reader sees in place of a URL the export did not record.
PLACEHOLDER = "source URL not recorded"

INVALID_SCHEME = (
    "ftp://source.example.test/records",
    "file:///tmp/payload.json",
    "javascript:alert(1)",
    "mailto:someone@source.example.test",
)

MALFORMED = (
    "https://",
    "http:/source.example.test",
    "//source.example.test/records",
    "not a url",
    "https://source.example.test/has a space",
    "https://[::1",
    "https://source.example.test:not-a-port/records",
    # Markup inside a rejected value must come out as text, not as elements.
    'javascript:alert("<b>x</b>")',
)


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


class ProvenanceParser(HTMLParser):
    """Anchors, every element, and the visible text of one rendered provenance list."""

    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[dict[str, str | None]] = []
        self.tags: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        self.tags.append(tag)
        if tag == "a":
            self.anchors.append(dict(attrs))

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def parse(payloads: dict) -> ProvenanceParser:
    parser = ProvenanceParser()
    parser.feed(render.provenance_html(SHA, payloads))
    return parser


def check_non_clickable(label: str, payloads: dict, expected_text: str) -> int:
    bad = 0
    parsed = parse(payloads)
    text = "".join(parsed.text)
    bad += check(not parsed.anchors, f"{label} rendered an anchor: {parsed.anchors!r}")
    bad += check(expected_text in text, f"{label} was not rendered as text: {text!r}")
    bad += check(set(parsed.tags) <= {"ul", "li", "span"},
                 f"{label} produced unexpected markup: {sorted(set(parsed.tags))!r}")
    bad += check(f"sha256 {SHA}" in text and f"fetched {FETCHED_AT}" in text,
                 f"{label} lost the payload hash or its fetch date")
    return bad


def main() -> int:
    bad = 0
    for url in INVALID_SCHEME:
        bad += check_non_clickable(f"invalid-scheme URL {url!r}",
                                   {SHA: {"url": url, "fetched_at": FETCHED_AT}}, url)
    for url in MALFORMED:
        bad += check_non_clickable(f"malformed URL {url!r}",
                                   {SHA: {"url": url, "fetched_at": FETCHED_AT}}, url)

    bad += check_non_clickable("missing source field", {SHA: {"fetched_at": FETCHED_AT}}, PLACEHOLDER)
    bad += check_non_clickable("null source field", {SHA: {"url": None, "fetched_at": FETCHED_AT}},
                               PLACEHOLDER)
    bad += check_non_clickable("blank source field", {SHA: {"url": "   ", "fetched_at": FETCHED_AT}},
                               PLACEHOLDER)

    unknown = parse({})
    bad += check(not unknown.anchors and PLACEHOLDER in "".join(unknown.text),
                 "a hash with no payload entry did not fall back to the placeholder")

    # Control: the same renderer does link a valid URL, so the assertions above
    # are rejecting anchors it is able to produce rather than anchors it never makes.
    valid = "https://api.openalex.org/works?filter=openalex:W1|W2&per-page=50"
    control = parse({SHA: {"url": valid, "fetched_at": FETCHED_AT}})
    bad += check(len(control.anchors) == 1 and control.anchors[0].get("href") == valid,
                 f"control: a valid source URL did not render as one link: {control.anchors!r}")

    print("test_provenance_url_fallback:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
