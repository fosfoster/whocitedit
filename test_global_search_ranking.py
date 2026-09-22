#!/usr/bin/env python3
"""Coverage for rankGlobalMatches: exact canonical IDs/labels before substrings."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

APP_JS = Path(__file__).parent / "web" / "assets" / "app.js"

# Adversarial fixture: broad substring-only rows are seeded ahead of the exact
# canonical-ID / title / entity-name rows they must be outranked by. Each row
# also carries its original source index so we can assert both tiering and
# within-tier source-order preservation from the ranked output alone.
ROWS = [
    {"kind": "work", "id": "W1", "label": "A Broad Survey on Neural Networks Applications",
     "aliases": [], "sourceIndex": 0},
    {"kind": "work", "id": "W2", "label": "Neural Networks",
     "aliases": [], "sourceIndex": 1},
    {"kind": "author", "id": "A1", "label": "Neural Networks Research Group",
     "aliases": [], "sourceIndex": 2},
    {"kind": "institution", "id": "neural networks", "label": "Unrelated Institution Name",
     "aliases": [], "sourceIndex": 3},
    {"kind": "topic", "id": "T1", "label": "Extended Neural Networks Framework",
     "aliases": [], "sourceIndex": 4},
    {"kind": "work", "id": "W3", "label": "Neural Networks",
     "aliases": [], "sourceIndex": 5},
    {"kind": "topic", "id": "T2", "label": "Deep Learning meets Neural Networks",
     "aliases": [], "sourceIndex": 6},
    {"kind": "author", "id": "A2", "label": "Someone Else",
     "aliases": ["Neural Networks Alias"], "sourceIndex": 7},
    {"kind": "work", "id": "W4", "label": "Something else entirely",
     "aliases": ["also unrelated"], "sourceIndex": 8},
    {"kind": "author", "id": "A3", "label": "neural networks",
     "aliases": [], "sourceIndex": 9},
]

QUERY = "neural networks"

# Exact canonical-ID (institution "neural networks"), exact paper titles (W2,
# W3), and an exact entity name (author A3) must all precede every
# substring-only row, in source order within each tier.
EXPECTED_EXACT_IDS = ["W2", "neural networks", "W3", "A3"]
EXPECTED_SUBSTRING_IDS = ["W1", "A1", "T1", "T2", "A2"]
EXPECTED_ORDER = EXPECTED_EXACT_IDS + EXPECTED_SUBSTRING_IDS


def check(condition: bool, message: str) -> int:
    if condition:
        return 0
    print(f"  FAIL: {message}")
    return 1


def extract_ranker(source: str) -> str:
    """Pull the module body out of app.js's top-level IIFE for reuse in node.

    Reuses the real shipped implementation instead of reimplementing the
    ranking rules in Python, so this test exercises the actual client code.
    """
    start_marker = "(function () {"
    end_marker = "})();"
    start = source.index(start_marker) + len(start_marker)
    end = source.rindex(end_marker)
    body = source[start:end]
    return (
        "'use strict';\n"
        "var document = { querySelector: function () { return null; } };\n"
        + body
        + "\nmodule.exports = { rankGlobalMatches: rankGlobalMatches };\n"
    )


def run_node_ranking(tmp_dir: Path, client_source: str) -> list:
    harness_path = tmp_dir / "app_harness.js"
    harness_path.write_text(extract_ranker(client_source))

    driver_path = tmp_dir / "driver.js"
    driver_path.write_text(
        "const { rankGlobalMatches } = require(" + json.dumps(str(harness_path)) + ");\n"
        "const rows = " + json.dumps(ROWS) + ";\n"
        "const query = " + json.dumps(QUERY) + ";\n"
        "const ranked = rankGlobalMatches(rows, query);\n"
        "process.stdout.write(JSON.stringify(ranked.map(r => r.id)));\n"
    )
    result = subprocess.run(
        ["node", str(driver_path)], capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"node ranking harness failed: {result.stderr}")
    return json.loads(result.stdout)


def main() -> int:
    if shutil.which("node") is None:
        print("test_global_search_ranking: SKIPPED (node not available)")
        return 0

    bad = 0
    client = APP_JS.read_text()

    bad += check("function rankGlobalMatches(rows, query)" in client,
                 "app.js does not define rankGlobalMatches(rows, query)")

    tmp_dir = Path(__file__).parent / ".ranking_test_tmp"
    tmp_dir.mkdir(exist_ok=True)
    ranked_ids: list = []
    try:
        try:
            ranked_ids = run_node_ranking(tmp_dir, client)
        except RuntimeError as error:
            bad += check(False, str(error))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    bad += check(ranked_ids == EXPECTED_ORDER,
                 f"exact matches did not precede substring matches in source order: {ranked_ids}")
    bad += check("W4" not in ranked_ids, "a non-matching row was not excluded from the ranked result")
    bad += check(len(ranked_ids) == len(set(ranked_ids)), "ranked result contains duplicate rows")

    # The ranked (not raw) result must feed the renderer, and MAX_RESULTS must
    # apply to that ranked output rather than to the unranked source order.
    render_call = client.find("render(rankGlobalMatches(rows, query));")
    bad += check(render_call >= 0,
                 "the renderer is not fed the output of rankGlobalMatches")
    render_fn_start = client.find("function render(matches) {")
    slice_call = client.find("matches.slice(0, MAX_RESULTS)", render_fn_start)
    bad += check(render_fn_start >= 0 and slice_call > render_fn_start,
                 "MAX_RESULTS is not applied to the ranked matches inside the renderer")

    # Loading must still be deferred until a non-empty query, and only the
    # renderer-provided local index is fetched -- no new service/endpoint.
    empty_guard = client.find("if (!query) return;")
    global_load = client.find("loadGlobal(form.dataset.index)")
    bad += check(0 <= empty_guard < global_load,
                 "global index can be fetched before a non-empty query")
    bad += check(client.count("fetch(") == 2,
                 "an unexpected new fetch call suggests a new endpoint/service was introduced")
    bad += check("XMLHttpRequest" not in client and "WebSocket" not in client,
                 "app.js should not introduce any other network transport")

    print("test_global_search_ranking:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
