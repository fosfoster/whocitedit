#!/usr/bin/env bash
# Publish the rendered site to Cloudflare Pages. Operator only.
#
# This file is in `policy.deny_paths` along with the rest of `tools/`: a builder
# that could edit the deploy could publish, and publishing is a human decision.
#
# THE FILE COUNT IS THE CONSTRAINT, not the byte size. Cloudflare Pages caps a
# deployment at 20,000 files on the Free plan. This site is one `index.html` per
# route plus a handful of assets -- 9,916 files at 3,000 works. The same site as
# a Next.js static export would be roughly nine files per route (`index.html`,
# `index.txt` and seven `__next.*.txt` prefetch payloads), which is ~89,000
# files and a deploy that fails rather than one that is slow. Check before
# widening the corpus.
set -euo pipefail
cd "$(dirname "$0")/.."

set -a; . ~/.env/cloudflare.env; set +a

python3 render.py

files=$(find web/site -type f | wc -l | tr -d ' ')
echo "== $files files (Pages free-plan cap: 20,000)"
if [ "$files" -gt 19000 ]; then
  echo "!! within 1,000 files of the cap; widen the corpus and this deploy fails" >&2
  exit 1
fi
if [ -n "$(find web/site -type f -size +25M -print -quit)" ]; then
  echo "!! Pages rejects any single file over 25 MiB" >&2
  exit 1
fi

# Uploads are incremental across deploys, and a mid-upload failure is worth one
# plain retry before investigating: the first deploy of this site died at
# 2,000/9,916 with an empty error body and the identical command then completed,
# because everything already uploaded was skipped.
npx --yes wrangler@latest pages deploy web/site \
  --project-name whocitedit --branch main --commit-dirty=true

for path in / /methodology/ /works/ /authors/; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "https://whocitedit.com$path" || echo "000")
  echo "  $code  $path"
done
