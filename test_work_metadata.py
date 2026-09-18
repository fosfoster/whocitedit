#!/usr/bin/env python3
"""Offline work-page citation and CreativeWork metadata coverage."""
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


def work(**changes):
    value = {
        "id": "W123",
        "title": "Complete work",
        "year": 2024,
        "date": "2024-02-03",
        "doi": "https://doi.org/10.1000/complete",
        "source": {"id": "S456", "name": "Source publication"},
        "oa": {"url": "https://example.test/open.pdf", "license": None},
        "abstract": {"text": "SENTINEL ABSTRACT", "reason": "rendered"},
        "cited_by_count": 4,
        "in_corpus_cited_by": 1,
        "authors": [
            {"id": "A2", "name": "Second Author"},
            {"id": "A1", "name": "First Author"},
        ],
        "topics": [],
        "graph": {"nodes": [], "shown": 0, "available": 0},
        "quality": {"band": "complete", "sentence": "Complete", "evidence": []},
        "raw": None,
        "openalex_url": "https://openalex.org/W123",
    }
    value.update(changes)
    return value


def metadata(page):
    tags = {}
    for name, value in re.findall(r'<meta name="([^"]+)" content="([^"]*)">', page):
        tags.setdefault(name, []).append(html.unescape(value))
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
    return tags, match, json.loads(match.group(1)) if match else None


def render_work(value):
    return render.render_work(value, {}, {}, {}, {}, set())


def main() -> int:
    bad = 0

    complete = render_work(work())
    tags, block, ld = metadata(complete)
    canonical = "https://whocitedit.com/w/W123"
    bad += check(tags.get("citation_title") == ["Complete work"], "citation title is missing")
    bad += check(tags.get("citation_author") == ["Second Author", "First Author"],
                 "citation authors are not in source order")
    bad += check(tags.get("citation_publication_date") == ["2024-02-03"],
                 "citation publication date is missing")
    bad += check(tags.get("citation_doi") == ["https://doi.org/10.1000/complete"],
                 "citation DOI is missing")
    bad += check(tags.get("citation_public_url") == [canonical],
                 "citation public URL does not match canonical URL")
    bad += check(block is not None and ld["@type"] == "ScholarlyArticle", "CreativeWork JSON-LD is missing")
    ld = ld or {}
    bad += check(ld.get("@id") == canonical and ld.get("url") == canonical,
                 "CreativeWork canonical identifiers do not match")
    bad += check(ld.get("name") == "Complete work", "CreativeWork name is missing")
    bad += check([person["name"] for person in ld.get("author", [])] == ["Second Author", "First Author"],
                 "CreativeWork author order changed")
    bad += check(ld.get("datePublished") == "2024-02-03", "CreativeWork publication date is missing")
    bad += check(ld.get("isPartOf", {}).get("name") == "Source publication", "CreativeWork source is missing")
    bad += check(ld.get("sameAs") == "https://openalex.org/W123", "CreativeWork OpenAlex URL is missing")
    bad += check(any(item.get("propertyID") == "DOI" for item in ld.get("identifier", [])),
                 "CreativeWork DOI identifier is missing")
    bad += check("citation_pdf_url" not in tags, "open-access URL became a citation PDF URL")
    bad += check("SENTINEL ABSTRACT" not in "".join(sum(tags.values(), []))
                 and "SENTINEL ABSTRACT" not in (block.group(1) if block else ""),
                 "abstract leaked into metadata")

    sparse = render_work(work(
        authors=[], date=None, year=None, doi=None, source={"id": None, "name": None},
    ))
    sparse_tags, _, sparse_ld = metadata(sparse)
    sparse_ld = sparse_ld or {}
    bad += check("citation_author" not in sparse_tags and "citation_publication_date" not in sparse_tags
                 and "citation_doi" not in sparse_tags, "sparse work emitted empty citation values")
    bad += check("author" not in sparse_ld and "datePublished" not in sparse_ld
                 and "isPartOf" not in sparse_ld, "sparse work fabricated JSON-LD values")
    bad += check([item["propertyID"] for item in sparse_ld.get("identifier", [])] == ["OpenAlex"],
                 "sparse work emitted a DOI identifier")

    year_only_tags, _, year_only_ld = metadata(render_work(work(date=None, year=2025)))
    year_only_ld = year_only_ld or {}
    bad += check(year_only_tags.get("citation_publication_date") == ["2025"],
                 "publication year did not supply the citation date")
    bad += check(year_only_ld.get("datePublished") == "2025",
                 "publication year did not supply the CreativeWork date")

    hostile_title = '</script><img src=x onerror="alert(1)">'
    hostile_name = 'Ada </script><img src=x onerror="alert(1)">'
    hostile = render_work(work(title=hostile_title, authors=[{"id": "A1", "name": hostile_name}]))
    hostile_tags, hostile_block, hostile_ld = metadata(hostile)
    hostile_ld = hostile_ld or {}
    bad += check(hostile.count("</script>") == complete.count("</script>"),
                 "hostile value terminated the JSON-LD script")
    bad += check("<img src=x" not in hostile, "hostile value created markup")
    bad += check(hostile_tags.get("citation_title") == [hostile_title], "hostile citation title changed")
    bad += check(hostile_ld.get("name") == hostile_title
                 and hostile_ld.get("author", [{}])[0].get("name") == hostile_name,
                 "hostile JSON-LD values do not round-trip")
    bad += check(hostile_block is not None and "\\u003c/script\\u003e" in hostile_block.group(1),
                 "JSON-LD does not escape a closing script sequence")

    print("test_work_metadata:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
