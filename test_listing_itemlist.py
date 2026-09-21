#!/usr/bin/env python3
"""Offline ItemList JSON-LD coverage for the public browse listings."""
import json
import re
import sys

import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def browse_rows(kind: str, count: int) -> list[dict]:
    rows = []
    prefixes = {"works": "W", "authors": "A", "institutions": "I", "topics": "T"}
    for position in range(1, count + 1):
        ident = f"{prefixes[kind]}{position}"
        label = "Unsafe <name> & title" if position == 1 else f"{kind.title()} {position}"
        if kind == "works":
            rows.append({
                "id": ident, "title": label, "authors": ["Example Author"],
                "quality": {"band": "complete", "sentence": "Complete", "evidence": []},
                "year": 2024, "cited": position, "in_corpus_cited": position - 1,
            })
        elif kind == "authors":
            rows.append({
                "id": ident, "name": label, "band": "high", "works": position,
                "coauthors": position - 1, "cited": position,
            })
        elif kind == "institutions":
            rows.append({
                "id": ident, "name": label, "authors": position,
                "works": position + 1, "graph": position - 1,
            })
        else:
            rows.append({
                "id": ident, "name": label, "works": position,
                "authors": position - 1,
            })
    return rows


def metadata(page: str) -> tuple[str, list[str], list[dict]]:
    head = page.split("</head>", 1)[0]
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', head, re.S)
    return head, blocks, [json.loads(block) for block in blocks]


def main() -> int:
    bad = 0
    corpus = {"definition": {"name": "Synthetic corpus"}}
    specs = {
        "works": ("Papers", "w", "title"),
        "authors": ("Authors", "a", "name"),
        "institutions": ("Institutions", "i", "name"),
        "topics": ("Topics", "t", "name"),
    }

    for kind, (title, prefix, name_key) in specs.items():
        rows = browse_rows(kind, 401)
        page = render.render_browse(kind, rows, corpus)
        _, blocks, lists = metadata(page)
        item_list = next(
            (metadata for metadata in lists if metadata.get("@type") == "ItemList"),
            {},
        )
        canonical = render.canonical_url(f"{kind}/")
        items = item_list.get("itemListElement", [])
        expected_rows = rows[:400]

        expected_blocks = 2 if kind in {"works", "authors"} else 1
        bad += check(len(blocks) == expected_blocks,
                     f"{kind} head does not contain exactly {expected_blocks} JSON-LD blocks")
        bad += check(item_list.get("@context") == "https://schema.org"
                     and item_list.get("@type") == "ItemList",
                     f"{kind} JSON-LD is not an ItemList")
        bad += check(item_list.get("@id") == canonical and item_list.get("url") == canonical,
                     f"{kind} ItemList canonical identifiers do not match the browse page")
        bad += check(item_list.get("name") == title, f"{kind} ItemList name does not match the page title")
        bad += check(item_list.get("numberOfItems") == len(expected_rows) == len(items),
                     f"{kind} ItemList count does not match the 400 displayed rows")
        bad += check([item.get("position") for item in items] == list(range(1, len(expected_rows) + 1)),
                     f"{kind} ItemList positions are not contiguous and 1-based")

        expected_hrefs = [f"../{prefix}/{row['id']}/" for row in expected_rows]
        table = page.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
        table_hrefs = re.findall(r'<a href="(\.\./[wait]/[^"]+/)">', table)
        bad += check(table_hrefs == expected_hrefs,
                     f"{kind} table detail hrefs do not match its displayed rows")
        item_entities = [
            item.get("item") if isinstance(item.get("item"), dict) else {}
            for item in items
        ]
        bad += check(
            [(item.get("@id"), item.get("url"), item.get("name")) for item in item_entities]
            == [(render.canonical_url(f"{prefix}/{row['id']}/"),
                 render.canonical_url(f"{prefix}/{row['id']}/"), row[name_key])
                for row in expected_rows],
            f"{kind} ItemList entries do not match the table entity links",
        )
        bad += check("<" not in blocks[0] if blocks else False,
                     f"{kind} JSON-LD block contains raw '<' from entity data")

    works = browse_rows("works", 401)
    field = {
        "key": "synthetic-field",
        "name": "Synthetic field",
        "description": "A field used to test uncapped listing metadata.",
        "works": len(works),
    }
    page = render.render_field(field, works, corpus)
    _, blocks, lists = metadata(page)
    item_list = lists[0] if lists else {}
    canonical = render.canonical_url(f"fields/{field['key']}/")
    items = item_list.get("itemListElement", [])

    bad += check(len(blocks) == 1, "field head does not contain exactly one JSON-LD block")
    bad += check(item_list.get("@context") == "https://schema.org"
                 and item_list.get("@type") == "ItemList",
                 "field JSON-LD is not an ItemList")
    bad += check(item_list.get("@id") == canonical and item_list.get("url") == canonical,
                 "field ItemList canonical identifiers do not match the field page")
    bad += check(item_list.get("name") == field["name"],
                 "field ItemList name does not match the page title")
    bad += check(item_list.get("numberOfItems") == len(works) == len(items),
                 "field ItemList count does not match every displayed work")
    bad += check([item.get("position") for item in items] == list(range(1, len(works) + 1)),
                 "field ItemList positions are not contiguous and 1-based")

    expected_hrefs = [f"../../w/{work['id']}/" for work in works]
    table = page.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    table_hrefs = re.findall(r'<a href="(\.\./\.\./w/[^"]+/)">', table)
    bad += check(table_hrefs == expected_hrefs,
                 "field table detail hrefs do not match every work")
    item_entities = [
        item.get("item") if isinstance(item.get("item"), dict) else {}
        for item in items
    ]
    bad += check(
        [(item.get("@id"), item.get("url"), item.get("name")) for item in item_entities]
        == [(render.canonical_url(f"w/{work['id']}/"),
             render.canonical_url(f"w/{work['id']}/"), work["title"])
            for work in works],
        "field ItemList entries do not match the table entity links",
    )
    bad += check("<" not in blocks[0] if blocks else False,
                 "field JSON-LD block contains raw '<' from entity data")

    print("test_listing_itemlist:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
