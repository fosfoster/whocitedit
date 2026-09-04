#!/usr/bin/env bash
# The gate. ONE definition, called by both CI and `commands.test` in
# .swarmward/project.yaml, so a builder cannot pass a ticket that CI would fail.
#
# This file is in `policy.deny_paths`. A builder that could edit the gate could
# pass its own ticket by making the gate smaller, and that is not a theoretical
# failure mode -- it is the first thing a stuck builder reaches for.
set -euo pipefail
cd "$(dirname "$0")/.."

# A stale .pyc can make a mutated module pass against code that is no longer on
# disk. A gate that can run yesterday's code is not a gate.
export PYTHONDONTWRITEBYTECODE=1
find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true

PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY=python3

fail=0
count=0

echo "== Python tests"
# Every test_*.py, not a hand-listed subset. A test file that exists and is never
# run is a gate that has quietly stopped being one -- it happened twice in
# pubfig-content, which is where this loop comes from.
for t in test_*.py; do
  [ -e "$t" ] || continue
  count=$((count + 1))
  printf '  %-28s ' "$t"
  if out=$("$PY" "$t" 2>&1); then
    echo "ok"
  else
    echo "FAIL"
    echo "$out" | sed 's/^/      /'
    fail=1
  fi
done
if [ "$count" -eq 0 ]; then
  echo "  no test_*.py found — that is a broken checkout, not a clean run" >&2
  exit 1
fi
echo "  ($count test files)"

# THE CORPUS FLOOR. `render.py` succeeds on an empty corpus, so without this a
# ticket could be passed by deleting web/data and the gate would go green on a
# site with no pages in it. These numbers are a floor, not a target: the corpus
# only ever grows, and a drop below them is either a bad export or a deletion.
echo "== Corpus floor"
"$PY" - <<'PYEOF'
import json, pathlib, sys
data = pathlib.Path("web/data")
floors = {"works-index.json": 2500, "authors-index.json": 5000}
bad = 0
for name, floor in floors.items():
    path = data / name
    if not path.exists():
        print(f"  MISSING {name}"); bad = 1; continue
    n = len(json.loads(path.read_text()))
    print(f"  {name:22} {n:>6}  (floor {floor})")
    if n < floor:
        print(f"  FAIL: {name} holds {n}, below the floor of {floor}"); bad = 1
corpus = json.loads((data / "corpus.json").read_text())
for key in ("identity_notes", "identity_bands", "counts", "sources"):
    if key not in corpus:
        print(f"  FAIL: corpus.json is missing {key}"); bad = 1
sys.exit(bad)
PYEOF

# The committed bundle is an artefact in the repository; this is what stops a
# stale one shipping. Pure Python: no Node, no network.
echo "== Island bundle"
"$PY" tools/bundle_hash.py || fail=1

echo "== Render"
"$PY" render.py

exit "$fail"
