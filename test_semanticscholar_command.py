#!/usr/bin/env python3
"""Fixture-only tests for the operator-only Semantic Scholar command."""
import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

import harvest


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (harvest.ROOT, harvest.SemanticScholarClient, harvest.Client,
             harvest.harvest_works, harvest.harvest_authors)
    try:
        harvest.ROOT = tmp
        raw = tmp / "harvest" / "raw"
        raw.mkdir(parents=True)
        (raw / "openalex-works.json").write_text(json.dumps({"results": [{
            "doi": "10.5555/source-paper", "authorships": [],
        }]}))

        semantic_clients = []

        class FakeSemanticScholarClient:
            def __init__(self):
                self.spent = 0
                self.budget = 3
                self.references_seen = []
                semantic_clients.append(self)

            @property
            def remaining(self):
                return self.budget - self.spent

            def references(self, doi):
                self.references_seen.append(doi)
                self.spent += 1

        harvest.SemanticScholarClient = FakeSemanticScholarClient
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = harvest.main(["harvest.py", "semanticscholar"])

        text = output.getvalue()
        bad += check(result == 0, "semanticscholar command returned failure")
        bad += check(len(semantic_clients) == 1,
                     "semanticscholar command did not construct exactly one client")
        bad += check(semantic_clients[0].references_seen == ["10.5555/source-paper"],
                     "semanticscholar command did not dispatch the stored DOI to its helper")
        bad += check("== semanticscholar" in text,
                     "semanticscholar command did not identify its pass")
        bad += check("== done: 1 requests spent, 2 left today" in text,
                     "semanticscholar command did not report spent and remaining requests")

        class FakeOpenAlexClient:
            mailto = "operator@example.com"

            def __init__(self):
                self.spent = 0
                self.remaining = 100

        dispatched = []

        def record_works(client):
            dispatched.append(("works", client))

        def record_authors(client):
            dispatched.append(("authors", client))

        harvest.Client = FakeOpenAlexClient
        harvest.harvest_works = record_works
        harvest.harvest_authors = record_authors
        semantic_clients.clear()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = harvest.main(["harvest.py", "all"])

        bad += check(result == 0, "all command returned failure")
        bad += check([name for name, _ in dispatched] == ["works", "authors"],
                     "all command no longer dispatches only OpenAlex works and authors")
        bad += check(not semantic_clients,
                     "all command constructed a Semantic Scholar client")

        readme = (Path(__file__).parent / "README.md").read_text()
        bad += check("python3 harvest.py semanticscholar" in readme,
                     "README does not name the Semantic Scholar command")
        bad += check("bounded operator-only network pass" in readme,
                     "README does not describe the bounded operator-only network pass")
        bad += check("retains each response verbatim" in readme
                     and "payload hash" in readme and "fetch time" in readme,
                     "README does not describe retained Semantic Scholar provenance")
        bad += check("derive.py" in readme and "source-attributed" in readme
                     and "citation.sources" in readme,
                     "README does not connect stored assertions to attributed citation edges")
    finally:
        (harvest.ROOT, harvest.SemanticScholarClient, harvest.Client,
         harvest.harvest_works, harvest.harvest_authors) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_semanticscholar_command:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
