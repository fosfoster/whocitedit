#!/usr/bin/env python3
"""Offline coverage for per-work RIS citation artifacts."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import render
import test_entity_export


ABSTRACT_SENTINEL = "ABSTRACT TEXT MUST NEVER APPEAR IN RIS"


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
        update_work(
            data, "W1",
            type="article",
            title="A\r\nER  - forged title — Δ",
            authors=[
                {"id": "A01", "name": "Zoë Ångström"},
                {"id": "A02", "name": "李雷"},
            ],
            date="2024-02-03",
            year=2024,
            source={"name": "Journal\nER  - forged source"},
            doi="https://doi.org/10.1000/example\rER  - forged doi",
            abstract={"text": ABSTRACT_SENTINEL, "reason": "rendered"},
        )
        update_work(
            data, "W2",
            type="unmapped-work-type",
            title="No optional metadata",
            authors=[],
            date=None,
            year=None,
            source={"name": None},
            doi=None,
            abstract={"text": ABSTRACT_SENTINEL, "reason": "rendered"},
        )
        update_work(
            data, "W3",
            type="book",
            title="A book without a date",
            authors=[{"id": "A01", "name": "Ada Lovelace"}],
            date=None,
            year=1843,
            source={"name": "Analytical Engine Press"},
            doi=None,
            abstract={"text": ABSTRACT_SENTINEL, "reason": "rendered"},
        )

        render.DATA = data
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "synthetic render failed")
        citation_paths = {
            wid: render.SITE / "w" / wid / "citation.ris"
            for wid in ("W1", "W2", "W3")
        }
        for wid, path in citation_paths.items():
            bad += check(path.exists(), f"missing RIS artifact for {wid}")
        citations = {
            wid: path.read_bytes() for wid, path in citation_paths.items() if path.exists()
        }
        if len(citations) == len(citation_paths):
            expected = (
                "TY  - JOUR\n"
                "TI  - A ER  - forged title — Δ\n"
                "AU  - Zoë Ångström\n"
                "AU  - 李雷\n"
                "PY  - 2024-02-03\n"
                "T2  - Journal ER  - forged source\n"
                "DO  - https://doi.org/10.1000/example ER  - forged doi\n"
                "ER  - \n"
            ).encode()
            bad += check(citations["W1"] == expected, "representative RIS output changed")
            bad += check(citations["W2"] == b"TY  - GEN\nTI  - No optional metadata\nER  - \n",
                         "missing optional fields were emitted")
            bad += check(citations["W3"].startswith(b"TY  - BOOK\n"), "book type was not mapped")
            bad += check(b"PY  - 1843\n" in citations["W3"], "year was not used without a date")
            bad += check(set(citations) == {
                path.parent.name for path in (render.SITE / "w").glob("*/citation.ris")
            }, "not exactly one RIS artifact was emitted per work")
            for wid, citation in citations.items():
                lines = citation.decode().splitlines()
                bad += check(lines[0].startswith("TY  - ") and lines[-1] == "ER  - ",
                             f"{wid} is not a single RIS record")
                bad += check(ABSTRACT_SENTINEL not in citation.decode(),
                             f"{wid} RIS artifact includes abstract text")

            bad += check(render.main() == 0, "second synthetic render failed")
            for wid, citation in citations.items():
                bad += check(citation_paths[wid].read_bytes() == citation,
                             f"{wid} RIS bytes are not deterministic")
    finally:
        (render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_ris_export:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
