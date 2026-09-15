#!/usr/bin/env python3
"""Author collaborator links must remain complete when graph labels are not."""
import html
import re
import sys
from pathlib import Path

import render


STYLE = Path(__file__).parent / "web" / "assets" / "style.css"


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def author(graph):
    return {
        "id": "A-FOCUS",
        "name": "Focus Author",
        "orcid": None,
        "openalex_url": "https://openalex.org/A-FOCUS",
        "confidence": {"band": "high", "evidence": []},
        "in_corpus": {"works": 1, "hindex": 1},
        "cited_by_count": 10,
        "works_count": 1,
        "graph": graph,
        "works": [{
            "id": "W1", "title": "Fixture work", "position": "first",
            "year": 2026, "cited": 10,
        }],
        "institutions": [],
    }


def declaration_block(css, selector):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    match = re.search(rf"(?m)^\s*{re.escape(selector)}\s*\{{([^}}]*)\}}", css)
    return match.group(1) if match else ""


def list_links(page):
    match = re.search(r'<ol class="collaborator-list">(.*?)</ol>', page, re.S)
    if not match:
        return [], -1
    return [
        (href, html.unescape(name), attrs)
        for attrs, href, name in re.findall(
            r'<li><a([^>]*) href="([^"]+)">(.*?)</a></li>', match.group(1), re.S
        )
    ], match.start()


def static_coauthor_nodes(page):
    figure = re.search(r'<figure class="graph" data-island="collaboration">(.*?)</figure>', page, re.S)
    if not figure:
        return [], "", -1
    svg = figure.group(1)
    nodes = [
        (href, html.unescape(name))
        for href, name in re.findall(
            r'<a class="node coauthor" href="([^"]+)"><circle[^>]*><title>(.*?)</title></circle>',
            svg,
            re.S,
        )
    ]
    return nodes, svg, figure.end()


def main() -> int:
    bad = 0
    # The source order is the collaboration-weight ranking. It deliberately is
    # neither alphabetical nor coordinate-derived, and identical positions make
    # the greedy SVG label pass drop at least one collaborator label.
    collaborators = [
        ("A-Z", "Zelda Zenith", 90),
        ("A-A", "Ada Alpha", 80),
        ("A-M", "Mira Middle", 70),
    ]
    graph = {
        "width": 400,
        "height": 220,
        "nodes": [
            {"id": "A-FOCUS", "label": "Focus Author", "kind": "focus", "cited": 100, "x": 200, "y": 110},
            *[
                {"id": ident, "label": name, "kind": "coauthor", "cited": cited, "x": 200, "y": 110}
                for ident, name, cited in collaborators
            ],
        ],
        "edges": [],
        "shown": len(collaborators),
        "available": len(collaborators),
    }
    page = render.render_author(author(graph), {}, {"high": "High confidence"}, {}, set())
    expected = [(f"../{ident}/", name) for ident, name, _ in collaborators]
    nodes, svg, figure_end = static_coauthor_nodes(page)
    links, list_start = list_links(page)
    targets_by_name = {name: f"../{ident}/" for ident, name, _ in collaborators}

    # Compare the static list to every coauthor node, rather than only to the
    # graph input: each retained graph node must be linked exactly once and in
    # its ranking order.
    bad += check(nodes == expected,
                 "static SVG coauthor nodes do not preserve the retained collaborator ranking")
    bad += check([(href, name) for href, name, _ in links] == nodes,
                 "collaborator list does not match every static SVG coauthor node exactly and in order")
    bad += check(len({href for href, _, _ in links}) == len(links),
                 "collaborator list duplicates a retained collaborator")
    for href, name, attrs in links:
        tabindex = re.search(r'\btabindex\s*=\s*["\']?(-?\d+)', attrs, re.I)
        bad += check(href == targets_by_name.get(name),
                     f"collaborator {name} is not linked to its author page")
        bad += check(tabindex is None or int(tabindex.group(1)) >= 0,
                     f"collaborator {name} has a negative tab index")
    bad += check(figure_end >= 0 and list_start > figure_end,
                 "collaborator list is hidden inside the replaceable graph island")

    visual_labels = {
        html.unescape(label)
        for label in re.findall(r'<text class="node-label"[^>]*>(.*?)</text>', svg, re.S)
    }
    missing_visual_labels = {name for _, name, _ in collaborators} - visual_labels
    bad += check(missing_visual_labels,
                 "overlapping coordinates did not cause greedy SVG label placement to omit a collaborator")
    bad += check({name for _, name, _ in links} == {name for _, name, _ in collaborators},
                 "collaborator list lost names that are absent from visual SVG labels")

    css = STYLE.read_text()
    list_css = declaration_block(css, ".collaborator-list")
    focus_css = declaration_block(css, ".collaborator-list a:focus-visible")
    bad += check("display: grid" in list_css
                 and "repeat(auto-fit, minmax(" in list_css,
                 "collaborator list is not a responsive grid")
    bad += check(re.search(r"\boutline\s*:\s*(?!none\b)[^;]+", focus_css) is not None,
                 "collaborator list links have no visible focus selector")

    empty_graph = {
        "width": 400, "height": 220,
        "nodes": [{"id": "A-FOCUS", "label": "Focus Author", "kind": "focus", "cited": 100, "x": 200, "y": 110}],
        "edges": [], "shown": 0, "available": 0,
    }
    empty_page = render.render_author(author(empty_graph), {}, {"high": "High confidence"}, {}, set())
    empty_links, _ = list_links(empty_page)
    empty_nodes, _, _ = static_coauthor_nodes(empty_page)
    bad += check(not empty_links and not empty_nodes
                 and not re.findall(r'href="\.\./(?!\.\./)[^\"]+/"', empty_page),
                 "an author with no retained collaborators manufactured collaborator links")

    print("test_author_collaborators:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
