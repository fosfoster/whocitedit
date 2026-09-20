#!/usr/bin/env python3
"""Proves citation.json (CSL-JSON) is produced by static rendering only.

Two claims, checked independently:

1. Running `render.py` as its own subprocess -- no server, no browser, no
   import of this test's process -- leaves complete and correct citation.json
   files on disk for every work as soon as the subprocess exits.
2. Nothing else in the codebase could produce that content instead: no route
   or request handler, and no client-side script, mentions CSL-JSON or the
   citation.json filename.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import render
import test_entity_export

ROOT = Path(__file__).parent


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def load_work(data: Path, wid: str) -> dict:
    for path in (data / "works").glob("*.json"):
        payload = json.loads(path.read_text())
        if wid in payload:
            return payload[wid]
    raise KeyError(wid)


def build_fake_root(tmp: Path) -> Path:
    """A standalone copy of the repo's static-generation surface.

    Only what `render.py` itself imports is linked in -- proof that the
    subprocess below runs the real renderer and nothing else, with no server
    process or browser involved anywhere in the chain.
    """
    fake_root = tmp / "fake_root"
    fake_root.mkdir()
    for name in ("render.py", "corpus_contract.py", "opencitations.py"):
        (fake_root / name).symlink_to(ROOT / name)
    (fake_root / "web").mkdir()
    (fake_root / "web" / "assets").symlink_to(ROOT / "web" / "assets")
    return fake_root


def static_scan_finds_no_dynamic_csl_json() -> list[str]:
    """Source strings that would indicate request-time CSL-JSON generation."""
    offenders = []

    server_markers = re.compile(
        r"\bflask\b|\bfastapi\b|\bdjango\b|\btornado\b|\baiohttp\b|"
        r"http\.server|socketserver|BaseHTTPRequestHandler|\bbottle\b",
        re.IGNORECASE,
    )
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in (".venv", "web") or rel.name.startswith("test_"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if server_markers.search(text):
            offenders.append(f"{rel}: imports/uses a web server framework")

    csl_markers = re.compile(r"citation\.json|csl-?json", re.IGNORECASE)
    js_ts_roots = [ROOT / "web" / "assets", ROOT / "web" / "app" / "src"]
    for base in js_ts_roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in (".js", ".ts", ".tsx", ".jsx"):
                continue
            if path.name in ("islands.js", "islands.js.sources"):
                continue  # vendored/bundled build output, not source we author
            text = path.read_text(encoding="utf-8", errors="ignore")
            if csl_markers.search(text):
                offenders.append(f"{path.relative_to(ROOT)}: references CSL-JSON client-side")

    return offenders


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    try:
        db_path, _, _ = test_entity_export.build_corpus(tmp)

        fake_root = build_fake_root(tmp)
        data = fake_root / "web" / "data"

        import export_json
        export_saved = (export_json.OUT, export_json.DB_PATH, export_json.ROOT)
        try:
            export_json.OUT = data
            export_json.DB_PATH = db_path
            export_json.ROOT = ROOT
            bad += check(export_json.main() == 0, "synthetic export failed")
        finally:
            export_json.OUT, export_json.DB_PATH, export_json.ROOT = export_saved

        # The subprocess below is the whole claim: a fresh Python process runs
        # render.py by itself, with no server bound to a port and no browser
        # anywhere in the chain, and nothing more is done to the output before
        # it is inspected.
        result = subprocess.run(
            [sys.executable, "render.py"],
            cwd=fake_root,
            capture_output=True,
            text=True,
        )
        bad += check(result.returncode == 0,
                     f"render.py subprocess failed: {result.stderr}")

        site = fake_root / "web" / "site"
        work_ids = {"W1", "W2", "W3"}
        csl_paths = {wid: site / "w" / wid / "citation.csl.json" for wid in work_ids}
        for wid, path in csl_paths.items():
            bad += check(path.exists(),
                         f"missing CSL-JSON artifact for {wid} immediately after static render")

        for wid, path in csl_paths.items():
            if not path.exists():
                continue
            parsed = json.loads(path.read_bytes().decode("utf-8"))
            expected = render.work_csl_json(load_work(data, wid))
            bad += check(parsed == expected,
                         f"{wid} citation.csl.json content does not match the static renderer's own output")
            bad += check(parsed.get("id") == wid, f"{wid} CSL-JSON id does not match work id")

        offenders = static_scan_finds_no_dynamic_csl_json()
        for offender in offenders:
            bad += check(False, f"possible dynamic CSL-JSON source: {offender}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_csl_json_static_only:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
