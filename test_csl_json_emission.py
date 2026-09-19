#!/usr/bin/env python3
"""Offline coverage for the per-work citation.csl.json CSL-JSON artifact."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import render
import test_entity_export


UTF8_TITLE = "Δοκιμή — 李雷's naïve café résumé"


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def update_work(data: Path, wid: str, **changes) -> None:
    for path in (data / "works").glob("*.json"):
        payload = json.loads(path.read_text())
        if wid in payload:
            payload[wid].update(changes)
            path.write_text(json.dumps(payload, sort_keys=True))
            return
    raise KeyError(wid)


def load_work(data: Path, wid: str) -> dict:
    for path in (data / "works").glob("*.json"):
        payload = json.loads(path.read_text())
        if wid in payload:
            return payload[wid]
    raise KeyError(wid)


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (render.DATA, render.SITE, render.ASSETS)
    try:
        db_path, _, _ = test_entity_export.build_corpus(tmp)
        import export_json

        export_saved = (export_json.OUT, export_json.DB_PATH, export_json.ROOT)
        try:
            export_json.OUT = tmp / "data"
            export_json.DB_PATH = db_path
            export_json.ROOT = Path(__file__).parent
            bad += check(export_json.main() == 0, "synthetic export failed")
        finally:
            (export_json.OUT, export_json.DB_PATH, export_json.ROOT) = export_saved

        data = tmp / "data"
        update_work(data, "W1", title=UTF8_TITLE)

        render.DATA = data
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "synthetic render failed")

        work_ids = {"W1", "W2", "W3"}
        csl_paths = {wid: render.SITE / "w" / wid / "citation.csl.json" for wid in work_ids}
        for wid, path in csl_paths.items():
            bad += check(path.exists(), f"missing CSL-JSON artifact for {wid}")

        all_work_dirs = list((render.SITE / "w").iterdir())
        bad += check(
            {d.name for d in all_work_dirs} == work_ids,
            "unexpected extra work artifact directories",
        )
        for wdir in all_work_dirs:
            extra = {p.name for p in wdir.iterdir()} - {
                "index.html", "citation.bib", "citation.ris", "citation.csl.json",
            }
            bad += check(not extra, f"stray artifacts in w/{wdir.name}: {extra}")

        first_bytes = {wid: path.read_bytes() for wid, path in csl_paths.items()}

        for wid, raw in first_bytes.items():
            parsed = json.loads(raw.decode("utf-8"))
            bad += check(parsed == render.work_csl_json(load_work(data, wid)),
                         f"{wid} citation.csl.json does not match render.work_csl_json")
            bad += check(parsed.get("id") == wid, f"{wid} CSL-JSON id does not match work id")

        parsed_w1 = json.loads(first_bytes["W1"].decode("utf-8"))
        bad += check(parsed_w1["title"] == UTF8_TITLE,
                     "UTF-8 title did not round-trip through the CSL-JSON artifact")
        bad += check("\\u" not in first_bytes["W1"].decode("utf-8"),
                     "UTF-8 title was escaped as \\uXXXX instead of stored literally")

        bad += check(render.main() == 0, "second synthetic render failed")
        for wid, path in csl_paths.items():
            bad += check(path.read_bytes() == first_bytes[wid],
                         f"{wid} CSL-JSON bytes are not deterministic across renders")
    finally:
        (render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_csl_json_emission:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
