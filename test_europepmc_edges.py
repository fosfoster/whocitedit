#!/usr/bin/env python3
"""Europe PMC reference assertions union into citation.sources unchanged."""
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
            "fetched_at": "2026-09-16T00:00:00+00:00",
            "path": str(path.relative_to(root)),
        }, sort_keys=True) + "\n")
    return sha


def load(tmp: Path, payloads: list[tuple[dict, str]]) -> dict[tuple[str, str], list[str]]:
    for payload, url in payloads:
        store_payload(tmp, payload, url)
    derive.RAW = tmp / "raw"
    derive.MANIFEST = tmp / "manifest.jsonl"
    conn = db.connect(tmp / "corpus.db")
    derive.load(conn)
    conn.commit()
    rows = {
        (row["citing_id"], row["cited_id"]): json.loads(row["sources"])
        for row in conn.execute("SELECT citing_id, cited_id, sources FROM citation")
    }
    conn.close()
    return rows


def main() -> int:
    bad = 0
    saved = (derive.RAW, derive.MANIFEST)

    # First: OpenAlex + COCI only, no Europe PMC payload present at all. This
    # is the "before" snapshot every existing edge must survive unchanged.
    before_tmp = Path(tempfile.mkdtemp())
    try:
        before = load(before_tmp, [
            (OPENALEX, "fixture://openalex/citation-sources"),
            (COCI, "fixture://opencitations/references"),
        ])
    finally:
        derive.RAW, derive.MANIFEST = saved
        shutil.rmtree(before_tmp, ignore_errors=True)

    bad += check(before[("W1", "W2")] == ["openalex", "opencitations"],
                 "setup: the shared edge did not start with both source assertions")
    bad += check(before[("W1", "W3")] == ["opencitations"],
                 "setup: the COCI-only edge was not resolved")
    bad += check(before[("W4", "W1")] == ["openalex"],
                 "setup: the OpenAlex-only edge did not resolve")
    bad += check(before[("W4", "W3")] == ["openalex"],
                 "setup: the OpenAlex-only inner edge did not resolve")

    # Second: add the Europe PMC search + references fixtures (from t1),
    # plus an out-of-corpus reference, a self-referential pair, and a second
    # citing article (echoed via a second search result) whose reference is
    # asserted by no other source, to prove a Europe-PMC-only edge is made.
    search = copy.deepcopy(EUROPEPMC_SEARCH)
    search["resultList"]["result"].append({
        "id": "38000004", "source": "MED", "doi": "10.5555/reference-one",
        "title": "Corroborated reference (as citer)",
    })

    references = copy.deepcopy(EUROPEPMC_REFERENCES)
    references["referenceList"]["reference"].append({
        "id": "99999999", "source": "MED",
        "title": "Outside the corpus", "doi": "10.5555/does-not-exist",
    })
    references["referenceList"]["reference"].append({
        "id": "38000001", "source": "MED",
        "title": "Self-citation", "doi": "10.5555/source-paper",
    })

    only_references = {
        "version": "6.9", "hitCount": 1,
        "request": {"id": "38000004", "source": "MED"},
        "referenceList": {"reference": [{
            "id": "38000005", "source": "MED",
            "title": "Europe-PMC-only reference", "doi": "10.5555/openalex-only",
        }]},
    }

    tmp = Path(tempfile.mkdtemp())
    try:
        after = load(tmp, [
            (OPENALEX, "fixture://openalex/citation-sources"),
            (COCI, "fixture://opencitations/references"),
            (search, "fixture://europepmc/search"),
            (references, "fixture://europepmc/references"),
            (only_references, "fixture://europepmc/references-only"),
        ])
    finally:
        derive.RAW, derive.MANIFEST = saved
        shutil.rmtree(tmp, ignore_errors=True)

    # Triple-asserted edge: OpenAlex + OpenCitations + Europe PMC agree that
    # the source paper (W1, Europe PMC id 38000001/MED) cites reference one
    # (W2, 10.5555/reference-one).
    bad += check(after[("W1", "W2")] == ["europepmc", "openalex", "opencitations"],
                 "the triple-asserted edge did not union all three sources")

    # Europe-PMC-only would be true if COCI hadn't already asserted W1->W3;
    # confirm the union added europepmc without disturbing opencitations.
    bad += check(after[("W1", "W3")] == ["europepmc", "opencitations"],
                 "the Europe PMC assertion did not union onto the existing edge")

    # Every edge that existed before Europe PMC was present keeps its exact
    # sources and endpoints.
    bad += check(after[("W4", "W1")] == before[("W4", "W1")] == ["openalex"],
                 "an edge untouched by Europe PMC changed sources")
    bad += check(after[("W4", "W3")] == before[("W4", "W3")] == ["openalex"],
                 "an edge untouched by Europe PMC changed sources")

    # A Europe PMC reference outside the corpus makes no dangling edge, and
    # the self-referential pair makes no edge either.
    bad += check(("W1", "W1") not in after, "a self-referential Europe PMC pair made a citation")
    bad += check(all(cited != "10.5555/does-not-exist" for (_, cited) in after),
                 "an out-of-corpus Europe PMC reference made a dangling citation")

    # A Europe-PMC-only edge (W2 -> W4) is created with just that source.
    bad += check(after.get(("W2", "W4")) == ["europepmc"],
                 "a Europe-PMC-only edge was not created with just that source")

    bad += check(set(after) == {("W1", "W2"), ("W1", "W3"), ("W4", "W1"), ("W4", "W3"), ("W2", "W4")},
                 "Europe PMC changed the set of citation edges beyond the union")

    print("test_europepmc_edges:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
