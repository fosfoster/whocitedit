#!/usr/bin/env python3
"""Offline author-page Person JSON-LD metadata coverage."""
import html
import json
import re
import sys

import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def author(**changes):
    value = {
        "id": "A123",
        "name": "Ada Lovelace",
        "orcid": "0000-0002-1825-0097",
        "openalex_url": "https://openalex.org/A123",
        "confidence": {"band": "high", "evidence": []},
        "in_corpus": {"works": 1, "hindex": 1},
        "cited_by_count": 4,
        "works_count": 5,
        "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
        "works": [{
            "id": "W123", "title": "SENTINEL WORK TITLE", "position": "first",
            "year": 2024, "cited": 4,
        }],
        "institutions": [{
            "id": "I123", "name": "SENTINEL AFFILIATION", "first_year": 2024,
            "last_year": 2024,
        }],
    }
    value.update(changes)
    return value


def metadata(page):
    head = page.split("</head>", 1)[0]
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', head, re.S)
    return head, blocks, [json.loads(block) for block in blocks]


def render_author(value):
    return render.render_author(value, {}, {"high": "High confidence"}, {}, {"I123"})


def main() -> int:
    bad = 0
    canonical = "https://whocitedit.com/a/A123"

    complete = render_author(author())
    head, blocks, people = metadata(complete)
    bad += check(len(blocks) == 1, "author head does not contain exactly one JSON-LD block")
    person = people[0] if people else {}
    bad += check(person.get("@context") == "https://schema.org"
                 and person.get("@type") == "Person", "Person JSON-LD is missing")
    bad += check(person.get("@id") == canonical and person.get("url") == canonical,
                 "Person canonical identifiers do not match the author page")
    bad += check(person.get("name") == "Ada Lovelace"
                 and html.unescape(re.search(r"<h1>(.*?)</h1>", complete).group(1)) == person.get("name"),
                 "Person name does not match the rendered author name")
    bad += check(person.get("sameAs") == ["https://openalex.org/A123", "https://orcid.org/0000-0002-1825-0097"],
                 "Person OpenAlex or normalized ORCID identity is missing")
    bad += check("citation_" not in head and "SENTINEL WORK TITLE" not in head
                 and "SENTINEL AFFILIATION" not in head,
                 "author head contains work-only or non-identity text")

    work_page = render.render_work({
        "id": "W123", "title": "Work", "year": 2024, "date": None, "doi": None,
        "source": {"id": None, "name": None}, "oa": {"url": None, "license": None},
        "abstract": {"text": None, "reason": None}, "cited_by_count": 0,
        "in_corpus_cited_by": 0, "authors": [{"id": "A123", "name": "Ada Lovelace"}],
        "topics": [], "graph": {"nodes": [], "shown": 0, "available": 0},
        "quality": {"band": "complete", "sentence": "Complete", "evidence": []},
        "raw": None, "openalex_url": "https://openalex.org/W123",
    }, {}, {}, {}, {}, set())
    _, _, works = metadata(work_page)
    work_person = works[0].get("author", [{}])[0] if works else {}
    bad += check(work_person.get("@id") == canonical and work_person.get("url") == canonical,
                 "work-page Person reference does not use the author-page identity")

    missing = render_author(author(orcid=None))
    _, missing_blocks, missing_people = metadata(missing)
    missing_person = missing_people[0] if missing_people else {}
    bad += check(len(missing_blocks) == 1
                 and missing_person.get("sameAs") == ["https://openalex.org/A123"],
                 "missing ORCID changed or fabricated identity values")
    bad += check("identifier" not in missing_person and "orcid.org" not in missing,
                 "missing ORCID emitted an empty identifier")

    hostile_name = '</script><img src=x onerror="alert(1)">'
    hostile = render_author(author(name=hostile_name))
    _, hostile_blocks, hostile_people = metadata(hostile)
    hostile_person = hostile_people[0] if hostile_people else {}
    # Compare against a clean render's own script-tag count rather than a
    # hardcoded number, so this only fails if the hostile name adds a script
    # tag of its own, not whenever the shared page chrome gains one.
    bad += check(hostile.count("</script>") == complete.count("</script>")
                 and "<img src=x" not in hostile,
                 "hostile name escaped the JSON-LD script")
    bad += check(hostile_person.get("name") == hostile_name
                 and hostile_blocks and "\\u003c/script\\u003e" in hostile_blocks[0],
                 "hostile Person name does not round-trip safely")

    print("test_author_metadata:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
