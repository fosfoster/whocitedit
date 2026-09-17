#!/usr/bin/env python3
"""An exported payload's source URL is judged on its own, with no rendering in the loop.

`payloads.json` maps a content hash to the URL those bytes came from, and that
URL is exported from the harvest manifest without inspection: a synthetic
corpus records a `file://` source, an older release recorded no URL at all, and
a hand-edited one can record a string no browser would resolve. This gate calls
the validator directly and holds it to one rule -- true only for an absolute
http or https URL naming a host, false for every relative reference, every
other scheme, every malformed string, and a source field that is null or
absent. Being pure is part of the contract, so the gate also checks that a call
answers the same way twice and leaves the exported record it read untouched.
"""
import copy
import sys

import render

# Absolute, http or https, naming a host: what a reader could paste and follow.
# The long one is the exported shape, a 50-id OR-filter carrying percent
# escapes, query separators and a fragment.
ABSOLUTE_HTTP = (
    "https://api.openalex.org/works/W1",
    "http://api.openalex.org/works/W1",
    "https://api.openalex.org",
    "https://api.openalex.org/",
    "https://api.openalex.org:8443/works/W1",
    "http://127.0.0.1:8080/works",
    "https://api.openalex.org/authors?filter=openalex_id%3AA1%7CA2"
    "&select=id%2Corcid&per-page=50&mailto=reader%40example.org#cursor",
    # RFC 3986 makes the scheme case-insensitive; this is still absolute https.
    "HTTPS://API.OpenAlex.ORG/works/W1",
)

# A reference that only resolves against a base the export does not carry. The
# protocol-relative one is the trap: it has a host but no scheme, so what it
# means depends on the page that happens to embed it.
RELATIVE = (
    "/works/W1",
    "works/W1",
    "../W1",
    "./W1",
    "//api.openalex.org/works/W1",
    "?filter=openalex_id%3AA1",
    "#cursor",
    "api.openalex.org/works/W1",
)

# Absolute and well formed, and still not a source a reader can follow from a
# published page.
OTHER_SCHEMES = (
    "ftp://api.openalex.org/works/W1",
    "file:///harvest/raw/W1.json",
    "file://W1",
    "javascript:alert(1)",
    "mailto:reader@example.org",
    "data:text/plain,W1",
    "ws://api.openalex.org/works/W1",
    "httpsx://api.openalex.org/works/W1",
)

# Strings that claim to be http(s) URLs and are not: no authority at all, a host
# that cannot be parsed, a port that is not a port, and whitespace or control
# characters a browser strips before resolving -- so the URL it fetches would
# not be the URL this site displayed.
MALFORMED = (
    "",
    "   ",
    "not a url",
    "https://",
    "http://",
    "https:",
    "http:/api.openalex.org",
    "https:api.openalex.org",
    "http:///works/W1",
    "https://@/works/W1",
    "https://:8443/works/W1",
    "https://[::1",
    "https://api.openalex.org:notaport/works/W1",
    "https://api.openalex.org:99999/works/W1",
    "https://api openalex.org/works/W1",
    " https://api.openalex.org/works/W1",
    "https://api.openalex.org/works/W1\n",
    "https://api.openalex.org/works\tW1",
    "https://api.openalex.org/works/\x00W1",
)

# No source field, or one exported as null. Anything that is not a string is the
# same absence wearing a different type, and is not guessed at either.
MISSING = (None, 0, 1, True, False, [], {}, b"https://api.openalex.org/works/W1")

# Exported payload records, shaped like `payloads.json`: a hash mapped to the
# URL those bytes were fetched from and when. Only the first is followable.
FOLLOWABLE, NULL_URL, NO_URL, LOCAL_FILE, RELATIVE_URL = (char * 64 for char in "abcde")
PAYLOADS = {
    FOLLOWABLE: {"url": "https://api.openalex.org/works/W1",
                 "fetched_at": "2026-09-01T01:02:03+00:00"},
    NULL_URL: {"url": None, "fetched_at": "2026-09-02T04:05:06+00:00"},
    # A release that stored the fetch time before it learned the URL.
    NO_URL: {"fetched_at": "2026-09-03T07:08:09+00:00"},
    LOCAL_FILE: {"url": "file:///harvest/raw/W1.json",
                 "fetched_at": "2026-09-04T10:11:12+00:00"},
    RELATIVE_URL: {"url": "/works/W1", "fetched_at": "2026-09-05T13:14:15+00:00"},
}
UNRESOLVED = "f" * 64  # named by a work and absent from the payload map


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def main() -> int:
    bad = 0

    for url in ABSOLUTE_HTTP:
        bad += check(render.valid_source_url(url) is True,
                     f"an absolute http(s) source URL was rejected: {url!r}")

    for label, values in (
        ("a relative URL", RELATIVE),
        ("a non-http(s) scheme", OTHER_SCHEMES),
        ("a malformed string", MALFORMED),
        ("a missing source field", MISSING),
    ):
        for value in values:
            bad += check(render.valid_source_url(value) is False,
                         f"{label} was accepted as a source URL: {value!r}")

    # Read the way a page reads it: the `url` off an exported payload record,
    # which may be null, absent, or a value only the harvester could follow.
    before = copy.deepcopy(PAYLOADS)
    expected = {FOLLOWABLE: True, NULL_URL: False, NO_URL: False,
                LOCAL_FILE: False, RELATIVE_URL: False}
    for sha, want in expected.items():
        got = render.valid_source_url(PAYLOADS[sha].get("url"))
        bad += check(got is want,
                     f"the exported source URL {PAYLOADS[sha].get('url')!r} on payload "
                     f"{sha[:8]} validated as {got}, expected {want}")
    bad += check(render.valid_source_url(PAYLOADS.get(UNRESOLVED, {}).get("url")) is False,
                 "a hash with no exported payload was treated as having a source URL")

    # Pure: same answer twice, and the record it was read from is unchanged.
    bad += check(
        all(render.valid_source_url(PAYLOADS[sha].get("url")) is want
            for sha, want in expected.items()),
        "validating an exported source URL twice did not give the same answer",
    )
    bad += check(PAYLOADS == before,
                 "validation mutated the exported payload records it was given")

    print("test_provenance_url_validation:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
