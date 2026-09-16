#!/usr/bin/env python3
"""Hermetic collection-wide provenance and citation-source audit.

The small synthetic pipeline test proves that the export and renderer can carry
provenance.  This gate instead reads the committed release, renders it into a
temporary directory, and checks every indexed work and author against the
reader-visible result.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
from html.parser import HTMLParser
import json
import shutil
import sys
import tempfile
from pathlib import Path

import render


ROOT = Path(__file__).parent
DATA = ROOT / "web" / "data"
ASSETS = ROOT / "web" / "assets"
HASH_LENGTH = 64
SOURCE_FIELDS = ("name", "url", "license", "role")


class ContractError(AssertionError):
    """A committed export or its rendered reader view violates the contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"could not read {path.relative_to(ROOT)}: {error}") from error


def indexed_ids(kind: str) -> set[str]:
    index = read_json(DATA / f"{kind}-index.json")
    require(isinstance(index, list), f"{kind} index is not a list")
    ids = [row.get("id") for row in index if isinstance(row, dict)]
    require(len(ids) == len(index) and all(isinstance(entity_id, str) and entity_id for entity_id in ids),
            f"{kind} index contains a row without an ID")
    duplicates = sorted(entity_id for entity_id, count in Counter(ids).items() if count != 1)
    require(not duplicates, f"{kind} index repeats IDs: {duplicates[:5]}")
    return set(ids)


def shard_records(kind: str, expected_ids: set[str]) -> dict[str, dict]:
    directory = DATA / kind
    paths = sorted(directory.glob("*.json"))
    require(paths, f"no {kind} shards were committed")
    occurrences = Counter()
    records = {}
    for path in paths:
        shard = read_json(path)
        require(isinstance(shard, dict), f"{kind} shard {path.name} is not an object")
        for entity_id, record in shard.items():
            require(isinstance(entity_id, str) and entity_id,
                    f"{kind} shard {path.name} has an invalid key")
            require(isinstance(record, dict),
                    f"{kind} {entity_id} in {path.name} is not an object")
            require(record.get("id") == entity_id,
                    f"{kind} shard key {entity_id} disagrees with its record ID")
            occurrences[entity_id] += 1
            records[entity_id] = record

    duplicates = sorted(entity_id for entity_id, count in occurrences.items() if count != 1)
    require(not duplicates, f"{kind} IDs do not occur exactly once across shards: {duplicates[:5]}")
    actual_ids = set(occurrences)
    require(actual_ids == expected_ids,
            f"{kind} index/shard membership differs; "
            f"missing={sorted(expected_ids - actual_ids)[:5]}, "
            f"unexpected={sorted(actual_ids - expected_ids)[:5]}")
    return records


def hashes(value, context: str) -> set[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    elif value is None:
        values = []
    else:
        raise ContractError(f"{context} has an invalid payload hash value")
    require(values, f"{context} has no payload hash")
    require(all(isinstance(sha, str) and len(sha) == HASH_LENGTH
                and all(char in "0123456789abcdef" for char in sha.lower()) for sha in values),
            f"{context} does not carry complete SHA-256 hash(es)")
    return set(values)


def resolve_payload_hashes(value, payloads: dict, context: str) -> set[str]:
    resolved = hashes(value, context)
    for sha in resolved:
        payload = payloads.get(sha)
        require(isinstance(payload, dict), f"{context} names orphan payload hash {sha}")
        require(bool(payload.get("fetched_at")),
                f"payload {sha} named by {context} has no fetch date")
    return resolved


def resolve_author_hashes(author: dict, work_raw: dict[str, object], payloads: dict) -> set[str]:
    """Use the renderer's direct-or-linked-work provenance resolver unchanged."""
    author_id = author["id"]
    resolved, used_work_fallback = render.author_provenance(author, work_raw)
    if author.get("raw"):
        require(not used_work_fallback, f"author {author_id} ignored direct provenance")
    else:
        require(used_work_fallback, f"author {author_id} did not use linked-work provenance")
        require(author.get("works"), f"author {author_id} has neither direct nor linked-work provenance")
    return resolve_payload_hashes(resolved, payloads, f"author {author_id}")


def source_declarations(corpus: dict) -> dict[str, list[dict]]:
    """Keep declaration IDs separate from reader-facing source fields.

    Releases before the keyed t1 declaration are still renderable through the
    legacy ``sources`` list.  They cannot satisfy an asserted machine source
    ID, so an edge that supplies one will correctly fail this audit.
    """
    raw = corpus.get("citation_sources", corpus.get("sources", []))
    declarations: dict[str, list[dict]] = defaultdict(list)
    if isinstance(raw, dict):
        entries = raw.items()
    elif isinstance(raw, list):
        entries = ((source.get("id"), source) for source in raw if isinstance(source, dict))
    else:
        raise ContractError("citation-source declarations are neither an object nor a list")
    for key, declaration in entries:
        require(isinstance(declaration, dict), "citation-source declaration is not an object")
        source_id = declaration.get("id", key)
        if source_id:
            require(isinstance(source_id, str), "citation-source declaration has an invalid ID")
            declarations[source_id].append(declaration)
    return declarations


def declaration_for(source_id: str, declarations: dict[str, list[dict]]) -> dict:
    matches = declarations.get(source_id, [])
    require(len(matches) == 1,
            f"edge source {source_id!r} maps to {len(matches)} citation-source declarations")
    declaration = matches[0]
    require(all(declaration.get(field) for field in SOURCE_FIELDS),
            f"citation-source declaration {source_id!r} lacks reader-facing fields")
    require("citation edges" in declaration["role"],
            f"citation-source declaration {source_id!r} does not declare a citation-edge role")
    return declaration


def asserted_edge_sources(works: dict[str, dict]) -> set[str]:
    asserted = set()
    for work_id, work in works.items():
        graph = work.get("graph") or {}
        require(isinstance(graph, dict), f"work {work_id} graph is not an object")
        edges = graph.get("edges") or []
        require(isinstance(edges, list), f"work {work_id} graph edges are not a list")
        for edge in edges:
            require(isinstance(edge, dict), f"work {work_id} has a non-object graph edge")
            sources = edge.get("sources") or []
            require(isinstance(sources, list),
                    f"work {work_id} edge sources are not a list")
            require(all(isinstance(source_id, str) and source_id for source_id in sources),
                    f"work {work_id} has an invalid edge source ID")
            asserted.update(sources)
    return asserted


class VisibleRows(HTMLParser):
    """Collect methodology table text, excluding markup attributes."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[str] = []
        self.parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self.parts = []

    def handle_data(self, data: str) -> None:
        if self.parts is not None:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self.parts is not None:
            self.rows.append(" ".join("".join(self.parts).split()))
            self.parts = None


def visible_rows(document: str) -> list[str]:
    parser = VisibleRows()
    parser.feed(document)
    parser.close()
    return parser.rows


@contextmanager
def rendered_site():
    """Render only committed inputs to a disposable site, restoring globals."""
    saved = render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS
    temporary = Path(tempfile.mkdtemp())
    try:
        render.DATA = DATA
        render.SITE = temporary / "site"
        render.ASSETS = ASSETS
        require(render.main() == 0, "render.main() failed for the committed corpus")
        yield render.SITE
    finally:
        render.DATA, render.SITE, render.ASSETS, render.NAV_FIELDS = saved
        shutil.rmtree(temporary, ignore_errors=True)


def rendered_ids(site: Path, prefix: str) -> set[str]:
    directory = site / prefix
    require(directory.is_dir(), f"rendered site has no {prefix}/ directory")
    return {page.parent.name for page in directory.glob("*/index.html")}


def require_page_provenance(page: Path, resolved: set[str], payloads: dict, context: str) -> None:
    require(page.is_file(), f"{context} has no rendered page")
    document = page.read_text(encoding="utf-8")
    for sha in resolved:
        fetched_at = payloads[sha]["fetched_at"]
        require(f"sha256 {sha}" in document,
                f"{context} page does not display complete hash {sha}")
        require(f"fetched {fetched_at}" in document,
                f"{context} page does not display fetch date for {sha}")


def expect_rejection(label: str, action) -> None:
    try:
        action()
    except ContractError:
        return
    raise ContractError(f"negative control was accepted: {label}")


def negative_controls() -> None:
    """Exercise the three assertions even while legacy edges have no source IDs."""
    orphan = "f" * HASH_LENGTH
    expect_rejection("orphan payload hash",
                     lambda: resolve_payload_hashes(orphan, {}, "negative work"))
    expect_rejection(
        "author without direct or linked-work provenance",
        lambda: resolve_author_hashes({"id": "A-negative", "raw": None, "works": []}, {}, {}),
    )
    negative_edge = {
        "W-negative": {"graph": {"edges": [{"sources": ["not-declared"]}]}}
    }
    expect_rejection(
        "undeclared edge source ID",
        lambda: declaration_for(
            next(iter(asserted_edge_sources(negative_edge))),
            {},
        ),
    )


def main() -> int:
    try:
        corpus = read_json(DATA / "corpus.json")
        require(isinstance(corpus, dict), "corpus metadata is not an object")
        payloads = read_json(DATA / "payloads.json")
        require(isinstance(payloads, dict), "payload map is not an object")

        work_ids = indexed_ids("works")
        author_ids = indexed_ids("authors")
        works = shard_records("works", work_ids)
        authors = shard_records("authors", author_ids)
        counts = corpus.get("counts") or {}
        require(counts.get("works") == len(work_ids) == len(works),
                f"corpus work count {counts.get('works')} disagrees with committed indexes/shards")
        require(counts.get("authors") == len(author_ids) == len(authors),
                f"corpus author count {counts.get('authors')} disagrees with committed indexes/shards")

        work_hashes = {
            work_id: resolve_payload_hashes(work.get("raw"), payloads, f"work {work_id}")
            for work_id, work in works.items()
        }
        work_raw = {work_id: work.get("raw") for work_id, work in works.items()}
        author_hashes = {
            author_id: resolve_author_hashes(author, work_raw, payloads)
            for author_id, author in authors.items()
        }

        declarations = source_declarations(corpus)
        edge_sources = asserted_edge_sources(works)
        declared_for_edges = {
            source_id: declaration_for(source_id, declarations)
            for source_id in edge_sources
        }
        negative_controls()

        with rendered_site() as site:
            require(rendered_ids(site, "w") == work_ids,
                    "rendered work-page membership differs from the work index")
            require(rendered_ids(site, "a") == author_ids,
                    "rendered author-page membership differs from the author index")
            for work_id, resolved in work_hashes.items():
                require_page_provenance(site / "w" / work_id / "index.html", resolved, payloads,
                                        f"work {work_id}")
            for author_id, resolved in author_hashes.items():
                require_page_provenance(site / "a" / author_id / "index.html", resolved, payloads,
                                        f"author {author_id}")

            methodology = site / "methodology" / "index.html"
            require(methodology.is_file(), "methodology page was not rendered")
            rows = visible_rows(methodology.read_text(encoding="utf-8"))
            for source_id, declaration in declared_for_edges.items():
                matching_rows = [
                    row for row in rows
                    if all(str(declaration[field]) in row for field in SOURCE_FIELDS)
                ]
                require(len(matching_rows) == 1,
                        f"methodology page shows {len(matching_rows)} visible declarations for "
                        f"edge source {source_id!r}")
    except ContractError as error:
        print(f"test_full_corpus_provenance: FAILED: {error}")
        return 1

    print(
        "test_full_corpus_provenance: ok "
        f"(works={len(work_ids)}, authors={len(author_ids)}, edge_sources={len(edge_sources)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
