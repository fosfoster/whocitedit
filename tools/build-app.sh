#!/usr/bin/env bash
# Rebuild the committed island bundle. Operator/CI, never the gate.
#
# The bundle is committed to the repository on purpose. `render.py` is pure
# Python and `tools/check.sh` is hermetic, so the site can be rendered and
# published on a host with no Node at all -- which keeps the two failure modes
# that have cost this fleet real board-days (a broken `npm ci`, a wrong Node
# major) out of the path that produces the site. What the gate checks instead is
# that the committed bundle is not STALE, by comparing a hash of its sources.
set -euo pipefail
cd "$(dirname "$0")/.."

_want=$(tr -d '[:space:]' < web/.nvmrc 2>/dev/null || true)
for _d in "/opt/node${_want}/bin" "/opt/homebrew/opt/node@${_want}/bin"; do
  if [ -n "$_want" ] && [ -x "$_d/node" ]; then export PATH="$_d:$PATH"; break; fi
done

npm --prefix web/app ci
npm --prefix web/app run typecheck
npm --prefix web/app run lint
npm --prefix web/app run build
python3 tools/bundle_hash.py --write
echo "== bundle rebuilt and source hash recorded"
