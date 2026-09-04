#!/usr/bin/env bash
# Everything the gate needs, in one place, so CI and every build host install the
# same thing. Called by `commands.setup` in .swarmward/project.yaml and by the
# `test` job in .github/workflows/test.yml.
#
# There is deliberately nothing to install. `requirements.txt` is empty and this
# repo has no Node: the renderer, the exporter and the harvester are standard
# library only. That is not minimalism for its own sake -- two other content
# boards in this fleet carry charter comments about `npm ci` failures and
# `.nvmrc` mismatches that stopped them producing work for days, and a gate with
# no dependency tree cannot have that failure.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 --version
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
