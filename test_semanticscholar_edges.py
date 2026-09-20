#!/usr/bin/env python3
"""Semantic Scholar reference assertions union into citation.sources unchanged."""
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
CROSSREF_WORK_REFERENCES = json.loads((ROOT / "docs" / "fixtures" / "crossref" / "work-references.json").read_text())
ARXIV_QUERY = json.loads((ROOT / "docs" / "fixtures" / "arxiv" / "query.json").read_text())
SEMANTICSCHOLAR_REFERENCES = json.loads(
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

    # First: OpenAlex + COCI + Europe PMC + Crossref + arXiv only, no
    # Semantic Scholar payload present at all. This is the "before" snapshot
    # every existing edge must survive unchanged.
    before_tmp = Path(tempfile.mkdtemp())
    try:
        before = load(before_tmp, [
            (OPENALEX, "fixture://openalex/citation-sources"),
            (COCI, "fixture://opencitations/references"),
            (EUROPEPMC_SEARCH, "fixture://europepmc/search"),
            (EUROPEPMC_REFERENCES, "fixture://europepmc/references"),
            (CROSSREF_WORK_REFERENCES, "fixture://crossref/work-references"),
            (ARXIV_QUERY, "fixture://arxiv/query"),
        ])
    finally:
        derive.RAW, derive.MANIFEST = saved
        shutil.rmtree(before_tmp, ignore_errors=True)

    bad += check(before[("W1", "W2")] == ["arxiv", "crossref", "europepmc", "openalex", "opencitations"],
                 "setup: the shared edge did not start with all five source assertions")
    bad += check(before[("W1", "W3")] == ["crossref", "europepmc", "opencitations"],
                 "setup: the COCI/Europe PMC/Crossref edge was not resolved")
    bad += check(before[("W4", "W1")] == ["openalex"],
                 "setup: the OpenAlex-only edge did not resolve")
    bad += check(before[("W4", "W3")] == ["openalex"],
                 "setup: the OpenAlex-only inner edge did not resolve")

    # Second: add the committed Semantic Scholar references fixture
    # (source-paper -> reference-one, plus a self-pair and an out-of-corpus
    # DOI already baked in), plus a second, Semantic Scholar-only paper
    # envelope whose one reference is asserted by no other index, to prove a
    # semanticscholar-only edge is created.
    extra = copy.deepcopy(SEMANTICSCHOLAR_REFERENCES)
    extra["paperId"] = "0000000000000000000000000000000000009"
    extra["externalIds"] = {"DOI": "10.5555/openalex-only"}
    extra["references"] = [
        {"paperId": "0000000000000000000000000000000000008",
         "externalIds": {"DOI": "10.5555/reference-one"}},
    ]

    tmp = Path(tempfile.mkdtemp())
    try:
        after = load(tmp, [
            (OPENALEX, "fixture://openalex/citation-sources"),
            (COCI, "fixture://opencitations/references"),
            (EUROPEPMC_SEARCH, "fixture://europepmc/search"),
            (EUROPEPMC_REFERENCES, "fixture://europepmc/references"),
            (CROSSREF_WORK_REFERENCES, "fixture://crossref/work-references"),
            (ARXIV_QUERY, "fixture://arxiv/query"),
            (SEMANTICSCHOLAR_REFERENCES, "fixture://semanticscholar/references"),
            (extra, "fixture://semanticscholar/references-extra"),
        ])
    finally:
        derive.RAW, derive.MANIFEST = saved
        shutil.rmtree(tmp, ignore_errors=True)

    # Sextuple-asserted edge: OpenAlex + OpenCitations + Europe PMC +
    # Crossref + arXiv + Semantic Scholar all agree the source paper (W1)
    # cites reference one (W2).
    bad += check(
        after[("W1", "W2")] == ["arxiv", "crossref", "europepmc", "openalex", "opencitations", "semanticscholar"],
        "the sextuple-asserted edge did not union Semantic Scholar onto its existing sources",
    )

    # The fixture also asserts source-paper -> reference-two (W1 -> W3), so
    # that shared edge unions 'semanticscholar' onto its existing sources too.
    bad += check(after[("W1", "W3")] == ["crossref", "europepmc", "opencitations", "semanticscholar"],
                 "the shared W1->W3 edge did not union 'semanticscholar' onto its existing sources")

    # Every edge the Semantic Scholar fixtures assert nothing about keeps its
    # exact (byte-identical) sources and endpoints.
    bad += check(after[("W4", "W1")] == before[("W4", "W1")] == ["openalex"],
                 "an edge untouched by Semantic Scholar changed sources")
    bad += check(after[("W4", "W3")] == before[("W4", "W3")] == ["openalex"],
                 "an edge untouched by Semantic Scholar changed sources")

    # The self-referential Semantic Scholar reference (source-paper ->
    # itself) makes no edge, and the out-of-corpus DOI (does-not-exist)
    # makes no dangling citation either.
    bad += check(("W1", "W1") not in after, "a self-referential Semantic Scholar pair made a citation")
    bad += check(all(cited != "10.5555/does-not-exist" for (_, cited) in after),
                 "an out-of-corpus Semantic Scholar reference made a dangling citation")

    # A Semantic Scholar-only edge (W4 -> W2, from the extra paper envelope)
    # is created with just that source.
    bad += check(after.get(("W4", "W2")) == ["semanticscholar"],
                 "a Semantic Scholar-only edge was not created with just that source")

    bad += check(set(after) == set(before) | {("W4", "W2")},
                 "Semantic Scholar changed the set of citation edges beyond the union")

    print("test_semanticscholar_edges:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
