#!/usr/bin/env python3
"""Fetch the corpus from OpenAlex into `harvest/raw/`. Network; operator lane.

THIS IS NOT A BUILDER STEP. It needs the network, it spends a metered credit
allowance, and it writes files that are gitignored. `tools/check.sh` never calls
it. A builder works against the JSON in `web/data/` that a completed harvest
produced, which is why the gate is hermetic and why a bad day at OpenAlex cannot
turn into a red board.

What the corpus IS is committed, in `corpus.json`: the filter, the sort and the
bound. That file is the reviewable definition of what this site covers, so
"why is this paper here and not that one" has a diffable answer.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from openalex import Client, short_id

ROOT = Path(__file__).parent
CORPUS = json.loads((ROOT / "corpus.json").read_text())

# OpenAlex accepts an OR-list in a filter. 50 ids per call keeps the URL well
# inside any gateway's length limit while still costing one list request -- the
# difference between this and fetching authors one at a time is 50x the credits
# for identical data.
IDS_PER_CALL = 50

WORK_FIELDS = ",".join(
    [
        "id", "doi", "title", "publication_year", "publication_date", "type",
        "primary_location", "best_oa_location", "open_access", "authorships",
        "cited_by_count", "referenced_works", "abstract_inverted_index",
        "primary_topic", "topics",
    ]
)
AUTHOR_FIELDS = ",".join(
    ["id", "orcid", "display_name", "display_name_alternatives",
     "works_count", "cited_by_count", "last_known_institutions"]
)


def harvest_works(client: Client) -> int:
    seen = 0
    target = CORPUS["max_works"]
    for fetched in client.paginate(
        "works",
        {
            "filter": CORPUS["seed_filter"],
            "sort": CORPUS["seed_sort"],
            "select": WORK_FIELDS,
        },
        max_records=target,
    ):
        got = len(fetched.payload.get("results") or [])
        seen += got
        print(f"  works +{got} = {seen}/{target}  ({client.spent} credits)", flush=True)
        if seen >= target:
            break
    return seen


def author_ids_in_raw() -> list[str]:
    ids: set[str] = set()
    for path in sorted((ROOT / "harvest" / "raw").rglob("*.json")):
        payload = json.loads(path.read_text())
        for work in payload.get("results") or []:
            if "authorships" not in work:
                continue
            for a in work["authorships"]:
                aid = short_id(((a.get("author") or {}).get("id")))
                if aid:
                    ids.add(aid)
    return sorted(ids)


def harvest_authors(client: Client) -> int:
    ids = author_ids_in_raw()
    print(f"  {len(ids)} distinct authors referenced by the stored works")
    done = 0
    for i in range(0, len(ids), IDS_PER_CALL):
        chunk = ids[i : i + IDS_PER_CALL]
        client.page(
            "authors",
            {
                "filter": "openalex_id:" + "|".join(chunk),
                "select": AUTHOR_FIELDS,
                "per-page": IDS_PER_CALL,
            },
        )
        done += len(chunk)
        print(f"  authors {done}/{len(ids)}  ({client.spent} credits)", flush=True)
    return done


def main(argv: list[str]) -> int:
    what = argv[1] if len(argv) > 1 else "all"
    client = Client()
    if not client.mailto:
        # Not fatal, but the polite pool is free and the common pool is not
        # worth the response times. Say so rather than silently taking the
        # slower queue.
        print("! WHOCITEDIT_MAILTO is unset: requests go to the common pool", file=sys.stderr)

    if what in ("works", "all"):
        print("== works")
        harvest_works(client)
    if what in ("authors", "all"):
        print("== authors")
        harvest_authors(client)
    print(f"== done: {client.spent} credits spent, {client.remaining} left today")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
