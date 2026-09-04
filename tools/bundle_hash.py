#!/usr/bin/env python3
"""Hash the island bundle's inputs, so a stale committed bundle is a gate failure.

The bundle in `web/assets/islands.js` is a build artefact that lives in the
repository. That is a deliberate trade -- it keeps Node out of the path that
renders and publishes the site -- and its one real risk is someone editing the
TypeScript, committing, and shipping the previous bundle. Nothing about the diff
would look wrong.

So the sources are hashed into `web/assets/islands.js.sources` at build time,
and `tools/check.sh` recomputes it. The check needs no Node and no network.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAMP = ROOT / "web" / "assets" / "islands.js.sources"
INPUTS = [
    ROOT / "web" / "app" / "package.json",
    ROOT / "web" / "app" / "package-lock.json",
    ROOT / "web" / "app" / "vite.config.ts",
    ROOT / "web" / "app" / "tsconfig.json",
]


def digest() -> str:
    h = hashlib.sha256()
    files = [p for p in INPUTS if p.exists()]
    files += sorted((ROOT / "web" / "app" / "src").rglob("*"))
    for path in files:
        if not path.is_file():
            continue
        h.update(str(path.relative_to(ROOT)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def main(argv: list[str]) -> int:
    current = digest()
    if "--write" in argv:
        STAMP.write_text(current + "\n")
        print(f"islands.js.sources = {current[:16]}…")
        return 0
    if not (ROOT / "web" / "assets" / "islands.js").exists():
        print("  FAIL: web/assets/islands.js is missing", file=sys.stderr)
        return 1
    if not STAMP.exists():
        print("  FAIL: web/assets/islands.js.sources is missing", file=sys.stderr)
        return 1
    recorded = STAMP.read_text().strip()
    if recorded != current:
        print(
            "  FAIL: the committed island bundle is stale — web/app/src changed "
            "since it was built.\n         Run ./tools/build-app.sh and commit "
            "web/assets/islands.js with it.",
            file=sys.stderr,
        )
        return 1
    print(f"  islands.js matches its sources ({current[:16]}…)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
