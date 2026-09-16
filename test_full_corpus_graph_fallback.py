#!/usr/bin/env python3
"""Audit every committed populated graph's server-rendered fallback."""
from __future__ import annotations

from html.parser import HTMLParser
import json
import re
import sys
from pathlib import Path

from test_full_corpus_render import DATA, rendered_site


DETAIL_PREFIX = {"work": "w", "author": "a"}


def classes(attributes: dict[str, str | None]) -> set[str]:
    return set((attributes.get("class") or "").split())


class GraphPage(HTMLParser):
    """Collect the static graph contract from one rendered detail page."""

    def __init__(self):
        super().__init__()
        self.figures = []
        self.figure = None
        self.static_wrapper = None
        self.svg = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "figure" and "graph" in classes(attributes):
            self.figure = {"attributes": attributes, "wrappers": []}
            self.figures.append(self.figure)
            return
        if self.figure is None:
            return
        if tag == "div" and "static-graph" in classes(attributes):
            self.static_wrapper = {"attributes": attributes, "svgs": []}
            self.figure["wrappers"].append(self.static_wrapper)
            return
        if self.static_wrapper is None:
            return
        if tag == "svg":
            self.svg = {"attributes": attributes, "nodes": 0}
            self.static_wrapper["svgs"].append(self.svg)
        elif self.svg is not None and "node" in classes(attributes):
            self.svg["nodes"] += 1

    def handle_endtag(self, tag):
        if tag == "svg":
            self.svg = None
        elif tag == "div" and self.static_wrapper is not None:
            self.static_wrapper = None
        elif tag == "figure" and self.figure is not None:
            self.figure = None
            self.static_wrapper = None
            self.svg = None


def populated_payloads(kind: str):
    """Yield every shard payload whose graph meets render.svg_graph's threshold."""
    for shard in sorted((DATA / f"{kind}s").glob("*.json")):
        payloads = json.loads(shard.read_text(encoding="utf-8"))
        if not isinstance(payloads, dict):
            raise AssertionError(f"{kind} shard {shard.name} is not an object")
        for entity_id, payload in payloads.items():
            nodes = (payload.get("graph") or {}).get("nodes") or []
            if len(nodes) >= 2:
                yield entity_id, payload


def hidden(attributes: dict[str, str | None]) -> bool:
    style = attributes.get("style") or ""
    return (
        "hidden" in attributes
        or attributes.get("aria-hidden", "").lower() == "true"
        or "hidden" in classes(attributes)
        or re.search(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)", style, re.I)
        is not None
    )


def audit_entity(site: Path, kind: str, entity_id: str, payload: dict) -> list[str]:
    page = site / DETAIL_PREFIX[kind] / entity_id / "index.html"
    prefix = f"{kind} {entity_id}:"
    if not page.is_file():
        return [f"{prefix} rendered detail page is missing"]

    parsed = GraphPage()
    parsed.feed(page.read_text(encoding="utf-8"))
    parsed.close()
    failures = []
    if len(parsed.figures) != 1:
        return [f"{prefix} expected one graph figure, found {len(parsed.figures)}"]

    figure = parsed.figures[0]
    expected_island = "citation" if kind == "work" else "collaboration"
    if figure["attributes"].get("data-island") != expected_island:
        failures.append(
            f"{prefix} graph figure data-island is "
            f"{figure['attributes'].get('data-island')!r}, not {expected_island!r}"
        )

    wrappers = figure["wrappers"]
    if len(wrappers) != 1:
        return failures + [
            f"{prefix} expected one static-graph wrapper, found {len(wrappers)}"
        ]

    wrapper = wrappers[0]
    if hidden(wrapper["attributes"]):
        failures.append(f"{prefix} static-graph wrapper is hidden")

    svgs = wrapper["svgs"]
    if len(svgs) != 1:
        return failures + [
            f"{prefix} expected one inline SVG in the static-graph wrapper, found {len(svgs)}"
        ]

    svg = svgs[0]
    if svg["attributes"].get("role") != "img":
        failures.append(f"{prefix} static SVG does not have role=img")
    if not (svg["attributes"].get("aria-label") or "").strip():
        failures.append(f"{prefix} static SVG has no accessible label")

    expected_nodes = len((payload.get("graph") or {}).get("nodes") or [])
    if svg["nodes"] != expected_nodes:
        failures.append(
            f"{prefix} static node markup count is {svg['nodes']}, expected {expected_nodes}"
        )
    return failures


def main() -> int:
    try:
        payload_totals = {
            kind: sum(1 for _ in populated_payloads(kind))
            for kind in DETAIL_PREFIX
        }
        failures = []
        audited_totals = {kind: 0 for kind in DETAIL_PREFIX}
        with rendered_site() as site:
            for kind in DETAIL_PREFIX:
                for entity_id, payload in populated_payloads(kind):
                    audited_totals[kind] += 1
                    failures.extend(audit_entity(site, kind, entity_id, payload))
    except AssertionError as error:
        failures = [f"corpus render: {error}"]
        payload_totals = {}
        audited_totals = {}

    for kind in DETAIL_PREFIX:
        if audited_totals.get(kind) != payload_totals.get(kind):
            failures.append(
                f"{kind} totals: audited {audited_totals.get(kind)}, "
                f"payload-derived {payload_totals.get(kind)}"
            )

    if failures:
        print("test_full_corpus_graph_fallback: FAILED:")
        for failure in failures:
            print(f"  {failure}")
        return 1

    print(
        "test_full_corpus_graph_fallback: ok "
        f"(works={audited_totals['work']}, authors={audited_totals['author']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
