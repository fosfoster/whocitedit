#!/usr/bin/env python3
"""The CreativeWork JSON-LD block carries the work's cited ('reference') neighbours.

work_head_metadata never read w['graph'], so a work's outbound citation edges
were invisible to structured-data crawlers even though the page's own graph and
neighbour list showed them. This gate renders the head metadata from an
in-memory graph fixture and checks the 'citation' array in the emitted
<script type="application/ld+json"> block: exactly the 'reference' nodes,
canonical @id/url per entry, focus and 'citer' nodes excluded, no key at all
when there are no reference nodes, and a hostile label does not break out of
the script element.
"""
import json
import re
import sys

import render

LD_JSON = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.S
)


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def work(**changes) -> dict:
    base = {
        "id": "W1", "title": "Fixture Work", "year": 2024, "date": None, "doi": None,
        "source": {"id": None, "name": None}, "oa": {"url": None, "license": None},
        "abstract": {"text": None, "reason": None}, "cited_by_count": 0,
        "in_corpus_cited_by": 0, "authors": [], "topics": [],
        "graph": {"nodes": [], "shown": 0, "available": 0},
        "quality": {"band": "complete", "sentence": "Complete", "evidence": []},
        "raw": None, "openalex_url": "https://openalex.org/W1",
    }
    base.update(changes)
    return base


def creative_work(document: str) -> dict:
    match = LD_JSON.search(document)
    assert match, "no application/ld+json block found"
    return json.loads(match.group(1))


def main() -> int:
    bad = 0

    # Focus + two references + one citer: only the two references survive, in
    # exported node order, each with a canonical @id/url and passed-through label.
    nodes = [
        {"id": "W1", "label": "Focus", "kind": "focus"},
        {"id": "W2", "label": "First Reference", "kind": "reference"},
        {"id": "W3", "label": "Citing Paper", "kind": "citer"},
        {"id": "W4", "label": "Second Reference", "kind": "reference"},
    ]
    w = work(graph={"nodes": nodes, "shown": 3, "available": 3})
    doc = render.work_head_metadata(w, "https://example.org/w/W1/")
    cw = creative_work(doc)
    bad += check("citation" in cw, "no citation key emitted for a work with reference nodes")
    citation = cw.get("citation", [])
    bad += check(len(citation) == 2, f"expected exactly two citation entries, got {citation!r}")
    ids = [entry.get("@id") for entry in citation]
    bad += check(
        ids == [render.canonical_url("w/W2/"), render.canonical_url("w/W4/")],
        f"citation @id order does not match exported node order: {ids!r}",
    )
    for entry in citation:
        bad += check(entry.get("@type") == "CreativeWork",
                     f"citation entry {entry!r} is not typed CreativeWork")
        bad += check(entry.get("url") == entry.get("@id"),
                     f"citation entry {entry!r} has mismatched @id/url")
    names = [entry.get("name") for entry in citation]
    bad += check(
        names == ["First Reference", "Second Reference"],
        f"citation entry names do not pass through node labels as-is: {names!r}",
    )
    focus_or_citer_ids = {render.canonical_url("w/W1/"), render.canonical_url("w/W3/")}
    bad += check(
        not (focus_or_citer_ids & set(ids)),
        "focus or citer nodes leaked into the citation array",
    )

    # Empty graph: sparse works must not gain an empty citation key.
    empty_w = work(graph={"nodes": [], "shown": 0, "available": 0})
    empty_doc = render.work_head_metadata(empty_w, "https://example.org/w/W1/")
    empty_cw = creative_work(empty_doc)
    bad += check(
        "citation" not in empty_cw,
        "a work with no reference nodes emitted an empty citation key",
    )

    # A hostile reference label must not terminate the script element early, and
    # must round-trip through json.loads unchanged.
    hostile_label = 'Evil</script><script>alert(1)</script>'
    hostile_nodes = [
        {"id": "W1", "label": "Focus", "kind": "focus"},
        {"id": "W5", "label": hostile_label, "kind": "reference"},
    ]
    hostile_w = work(graph={"nodes": hostile_nodes, "shown": 1, "available": 1})
    hostile_doc = render.work_head_metadata(hostile_w, "https://example.org/w/W1/")
    bad += check(
        len(LD_JSON.findall(hostile_doc)) == 1,
        "a hostile reference label produced more or fewer than one ld+json script block",
    )
    hostile_cw = creative_work(hostile_doc)
    hostile_names = [entry.get("name") for entry in hostile_cw.get("citation", [])]
    bad += check(
        hostile_names == [hostile_label],
        f"hostile label did not round-trip through json.loads unchanged: {hostile_names!r}",
    )

    print("test_work_citation_jsonld:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
