#!/usr/bin/env python3
"""Offline institution-page Organization JSON-LD metadata coverage."""
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


def institution(**changes):
    value = {
        "id": "I123",
        "name": "Sentinel University",
        "metadata": {"ror": "https://ror.org/sentinel", "country_code": "US", "type": "education"},
        "authors": [{
            "id": "A123", "name": "SENTINEL AUTHOR NAME", "works": 1, "cited_by_count": 4,
            "confidence": {"band": "high", "evidence": []},
        }],
        "works": [{
            "id": "W123", "title": "SENTINEL WORK TITLE", "year": 2024, "cited": 4,
            "quality": {"band": "complete", "sentence": "Complete", "evidence": []},
        }],
        "graph": {"nodes": [], "edges": [], "shown": 0, "available": 0},
        "raw": None,
        "openalex_url": "https://openalex.org/I123",
    }
    value.update(changes)
    return value


def metadata(page):
    head = page.split("</head>", 1)[0]
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', head, re.S)
    return head, blocks, [json.loads(block) for block in blocks]


def render_institution(value):
    return render.render_institution(value, {}, {"A123"}, {"W123"})


def topic(**changes):
    value = {
        "id": "T123",
        "name": "Sentinel Topic",
        "metadata": {"field": "Sentinel Field", "domain": "Sentinel Domain"},
        "works": [{
            "id": "W123", "title": "SENTINEL WORK TITLE", "year": 2024, "cited": 4,
            "quality": {"band": "complete", "sentence": "Complete", "evidence": []},
        }],
        "authors": [{
            "id": "A123", "name": "SENTINEL AUTHOR NAME", "participation": 1, "cited_by_count": 4,
            "confidence": {"band": "high", "evidence": []},
        }],
        "raw": None,
        "openalex_url": "https://openalex.org/T123",
    }
    value.update(changes)
    return value


def render_topic(value):
    return render.render_topic(value, {}, {"W123"}, {"A123"})


def main() -> int:
    bad = 0
    canonical = "https://whocitedit.com/i/I123"

    complete = render_institution(institution())
    head, blocks, orgs = metadata(complete)
    bad += check(len(blocks) == 1, "institution head does not contain exactly one JSON-LD block")
    org = orgs[0] if orgs else {}
    bad += check(org.get("@context") == "https://schema.org"
                 and org.get("@type") == "Organization", "Organization JSON-LD is missing")
    bad += check(org.get("@id") == canonical and org.get("url") == canonical,
                 "Organization canonical identifiers do not match the institution page")
    bad += check(org.get("name") == "Sentinel University"
                 and html.unescape(re.search(r"<h1>(.*?)</h1>", complete).group(1)) == org.get("name"),
                 "Organization name does not match the rendered institution name")
    bad += check(org.get("sameAs") == ["https://openalex.org/I123", "https://ror.org/sentinel"],
                 "Organization OpenAlex or ROR identity is missing")
    bad += check("SENTINEL AUTHOR NAME" not in head and "SENTINEL WORK TITLE" not in head,
                 "institution head contains table-only, non-identity text")

    no_ror = render_institution(institution(metadata={"ror": None, "country_code": "US", "type": "education"}))
    _, no_ror_blocks, no_ror_orgs = metadata(no_ror)
    no_ror_org = no_ror_orgs[0] if no_ror_orgs else {}
    bad += check(len(no_ror_blocks) == 1
                 and no_ror_org.get("sameAs") == ["https://openalex.org/I123"],
                 "missing ROR changed or fabricated identity values")

    no_identity = render_institution(institution(
        metadata={"ror": None, "country_code": "US", "type": "education"}, openalex_url=None))
    _, _, no_identity_orgs = metadata(no_identity)
    no_identity_org = no_identity_orgs[0] if no_identity_orgs else {}
    bad += check("sameAs" not in no_identity_org,
                 "missing OpenAlex URL and ROR emitted an empty sameAs list")

    topic_canonical = "https://whocitedit.com/t/T123"

    complete_topic = render_topic(topic())
    topic_head, topic_blocks, topic_terms = metadata(complete_topic)
    bad += check(len(topic_blocks) == 1, "topic head does not contain exactly one JSON-LD block")
    term = topic_terms[0] if topic_terms else {}
    bad += check(term.get("@context") == "https://schema.org"
                 and term.get("@type") == "DefinedTerm", "DefinedTerm JSON-LD is missing")
    bad += check(term.get("@id") == topic_canonical and term.get("url") == topic_canonical,
                 "DefinedTerm canonical identifiers do not match the topic page")
    bad += check(term.get("name") == "Sentinel Topic"
                 and html.unescape(re.search(r"<h1>(.*?)</h1>", complete_topic).group(1)) == term.get("name"),
                 "DefinedTerm name does not match the rendered topic name")
    bad += check(term.get("sameAs") == ["https://openalex.org/T123"],
                 "DefinedTerm OpenAlex identity is missing")
    bad += check("SENTINEL AUTHOR NAME" not in topic_head and "SENTINEL WORK TITLE" not in topic_head,
                 "topic head contains table-only, non-identity text")

    no_openalex_topic = render_topic(topic(openalex_url=None))
    _, no_openalex_blocks, no_openalex_terms = metadata(no_openalex_topic)
    no_openalex_term = no_openalex_terms[0] if no_openalex_terms else {}
    bad += check(len(no_openalex_blocks) == 1 and "sameAs" not in no_openalex_term,
                 "missing OpenAlex URL emitted an empty or fabricated sameAs list")

    print("test_entity_head_metadata:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
