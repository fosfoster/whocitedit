#!/usr/bin/env python3
"""Gate every committed work's JSON-LD citations against its graph nodes."""
import json
from pathlib import Path
import re
import sys

import render

ROOT = Path(__file__).parent
WORKS_DIR = ROOT / "web" / "data" / "works"
WORKS_INDEX = ROOT / "web" / "data" / "works-index.json"
LD_JSON = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
EXPECTED_SHARD_COUNT = 100
EXPECTED_WORK_COUNT = 3000


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def creative_work(document):
    match = LD_JSON.search(document)
    return json.loads(match.group(1)) if match else None


def reference_urls(work):
    """Reference-node URLs in the exported-node order used by render."""
    urls = []
    seen = set()
    for node in (work.get("graph") or {}).get("nodes", []):
        if node.get("kind") != "reference":
            continue
        node_id = node.get("id")
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        urls.append(render.canonical_url(f"w/{node_id}/"))
    return urls


def main() -> int:
    bad = 0
    paths = sorted(WORKS_DIR.glob("*.json"))
    bad += check(len(paths) == EXPECTED_SHARD_COUNT,
                 f"found {len(paths)} work shards, expected {EXPECTED_SHARD_COUNT}")

    index = json.loads(WORKS_INDEX.read_text(encoding="utf-8"))
    indexed_urls = {
        render.canonical_url(f"w/{entry['id']}/")
        for entry in index
    }

    works_scanned = 0
    works_with_citations = 0
    citation_entries = 0

    for path in paths:
        shard = json.loads(path.read_text(encoding="utf-8"))
        for wid, work in shard.items():
            works_scanned += 1
            document = render.work_head_metadata(
                work, render.canonical_url(f"w/{wid}/")
            )
            ld = creative_work(document)
            bad += check(ld is not None, f"{wid}: no JSON-LD block emitted")
            if ld is None:
                continue

            expected_urls = reference_urls(work)
            has_citation = "citation" in ld
            if has_citation:
                works_with_citations += 1

            citations = ld.get("citation")
            bad += check(
                not has_citation or isinstance(citations, list),
                f"{wid}: citation is not an array: {citations!r}",
            )
            citations = citations if isinstance(citations, list) else []
            citation_entries += len(citations)

            actual_urls = []
            forbidden_urls = {render.canonical_url(f"w/{wid}/")}
            citer_urls = {
                render.canonical_url(f"w/{node['id']}/")
                for node in (work.get("graph") or {}).get("nodes", [])
                if node.get("kind") == "citer" and node.get("id")
            }
            # A neighbour can legitimately be both a reference and a citer in
            # the same graph. Its reference occurrence belongs in citation;
            # only a citer-only node is forbidden here.
            forbidden_urls.update(citer_urls - set(expected_urls))
            for position, entry in enumerate(citations, start=1):
                bad += check(isinstance(entry, dict),
                             f"{wid}: citation entry {position} is not an object: {entry!r}")
                if not isinstance(entry, dict):
                    continue
                entry_id = entry.get("@id")
                entry_url = entry.get("url")
                actual_urls.append(entry_id)
                bad += check(
                    entry_id == entry_url,
                    f"{wid}: citation entry {position} has mismatched @id/url: {entry!r}",
                )
                bad += check(
                    entry_id in indexed_urls and entry_url in indexed_urls,
                    f"{wid}: citation entry {position} does not resolve to an indexed canonical work URL: {entry!r}",
                )
                bad += check(
                    entry_id not in forbidden_urls,
                    f"{wid}: citation entry {position} is the focus work or a citer-only node: {entry!r}",
                )

            if expected_urls:
                bad += check(has_citation,
                             f"{wid}: reference nodes emitted no citation array")
                bad += check(
                    actual_urls == expected_urls,
                    f"{wid}: citation @id order {actual_urls!r} does not match reference nodes {expected_urls!r}",
                )
            else:
                bad += check(not has_citation,
                             f"{wid}: no reference nodes but citation key was emitted")

    bad += check(works_scanned == EXPECTED_WORK_COUNT,
                 f"scanned {works_scanned} works, expected {EXPECTED_WORK_COUNT}")
    bad += check(works_with_citations > 0,
                 "no works carried a citation array; corpus scan must not pass silently")

    print("work citation totals:")
    print(f"  works scanned: {works_scanned}")
    print(f"  works carrying a citation array: {works_with_citations}")
    print(f"  citation entries: {citation_entries}")
    print("test_full_corpus_work_citations:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
