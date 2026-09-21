#!/usr/bin/env python3
"""Fixture-only provenance coverage for every citation source."""
import copy
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import db
import derive


ROOT = Path(__file__).parent
OPENALEX = json.loads((ROOT / "docs" / "fixtures" / "openalex" / "citation-sources.json").read_text())
COCI = json.loads((ROOT / "docs" / "fixtures" / "opencitations" / "references.json").read_text())
EUROPEPMC_SEARCH = json.loads((ROOT / "docs" / "fixtures" / "europepmc" / "search.json").read_text())
EUROPEPMC_REFERENCES = json.loads((ROOT / "docs" / "fixtures" / "europepmc" / "references.json").read_text())
CROSSREF = json.loads((ROOT / "docs" / "fixtures" / "crossref" / "work-references.json").read_text())
ARXIV = json.loads((ROOT / "docs" / "fixtures" / "arxiv" / "query.json").read_text())
SEMANTICSCHOLAR = json.loads(
    (ROOT / "docs" / "fixtures" / "semanticscholar" / "references.json").read_text()
)


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def store_payload(root: Path, payload, url: str) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sha = hashlib.sha256(body).hexdigest()
    path = root / "raw" / sha[:2] / f"{sha}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    with (root / "manifest.jsonl").open("a") as manifest:
        manifest.write(json.dumps({
            "sha256": sha,
            "url": url,
            "fetched_at": "2026-09-20T00:00:00+00:00",
            "path": str(path.relative_to(root)),
        }, sort_keys=True) + "\n")
    return sha


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (derive.RAW, derive.MANIFEST)
    try:
        # This is a distinct stored COCI response that repeats the W1 -> W2
        # assertion. Its extra out-of-corpus reference changes its raw hash
        # without changing the in-corpus edge set.
        duplicate_coci = copy.deepcopy(COCI)
        duplicate_coci.append({
            "citing": "10.5555/source-paper",
            "cited": "10.5555/does-not-exist",
        })
        payload_hashes = {
            "openalex": store_payload(tmp, OPENALEX, "fixture://openalex/citation-sources"),
            "opencitations": store_payload(tmp, COCI, "fixture://opencitations/references"),
            "opencitations_duplicate": store_payload(
                tmp, duplicate_coci, "fixture://opencitations/references-duplicate"
            ),
            "europepmc_search": store_payload(tmp, EUROPEPMC_SEARCH, "fixture://europepmc/search"),
            "europepmc": store_payload(tmp, EUROPEPMC_REFERENCES, "fixture://europepmc/references"),
            "crossref": store_payload(tmp, CROSSREF, "fixture://crossref/work-references"),
            "arxiv": store_payload(tmp, ARXIV, "fixture://arxiv/query"),
            "semanticscholar": store_payload(
                tmp, SEMANTICSCHOLAR, "fixture://semanticscholar/references"
            ),
        }
        derive.RAW = tmp / "raw"
        derive.MANIFEST = tmp / "manifest.jsonl"
        conn = db.connect(tmp / "corpus.db")
        derive.load(conn)
        conn.commit()

        rows = {
            row["source"]: row["raw_sha"]
            for row in conn.execute(
                "SELECT source, raw_sha FROM citation_assertion "
                "WHERE citing_id = ? AND cited_id = ? ORDER BY source",
                ("W1", "W2"),
            )
        }
        expected = {
            "arxiv": payload_hashes["arxiv"],
            "crossref": payload_hashes["crossref"],
            "europepmc": payload_hashes["europepmc"],
            "openalex": payload_hashes["openalex"],
            "opencitations": min(
                payload_hashes["opencitations"], payload_hashes["opencitations_duplicate"]
            ),
            "semanticscholar": payload_hashes["semanticscholar"],
        }
        bad += check(rows == expected,
                     "each source assertion did not retain the payload that asserted W1 -> W2")

        citation_sources = json.loads(conn.execute(
            "SELECT sources FROM citation WHERE citing_id = ? AND cited_id = ?", ("W1", "W2")
        ).fetchone()["sources"])
        bad += check(citation_sources == sorted(rows),
                     "citation.sources was not derived from the persisted assertions")
        bad += check(len(rows) == 6,
                     "the shared fixture edge did not retain exactly one assertion per source")
        bad += check(conn.execute(
            "SELECT COUNT(*) FROM citation_assertion ca "
            "JOIN raw_payload rp ON rp.sha256 = ca.raw_sha "
            "WHERE ca.citing_id = ? AND ca.cited_id = ?", ("W1", "W2")
        ).fetchone()[0] == 6, "citation assertion hashes did not join raw_payload")
        bad += check(not conn.execute(
            "SELECT 1 FROM citation_assertion WHERE citing_id = cited_id"
        ).fetchone(), "a self-citation assertion was retained")
        bad += check(not conn.execute("PRAGMA foreign_key_check").fetchone(),
                     "citation assertions violate a foreign key")

        # The Crossref and Semantic Scholar fixtures each supply both kinds of
        # invalid reference, so neither can leak through provenance storage.
        bad += check(not conn.execute(
            "SELECT 1 FROM citation_assertion WHERE cited_id NOT IN (SELECT id FROM work)"
        ).fetchone(), "an out-of-corpus assertion was retained")
        conn.close()
    finally:
        derive.RAW, derive.MANIFEST = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_citation_assertion_provenance:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
