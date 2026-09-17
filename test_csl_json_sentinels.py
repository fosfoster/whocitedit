#!/usr/bin/env python3
"""Offline coverage for per-work CSL-JSON citation artifacts."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import render
import test_entity_export


ABSTRACT_SENTINEL = "CSL_ABSTRACT_MUST_NOT_APPEAR"
OTHER_SOURCE_SENTINEL = "CSL_OTHER_SOURCE_MUST_NOT_APPEAR"


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
        # Representative work: every optional field populated, including an
        # abstract and identifiers sourced from something other than the
        # citation metadata rendered on the work page.
        update_work(
            data, "W1",
            type="article",
            title="A representative work",
            authors=[
                {"id": "A01", "name": "Zoë Ångström"},
                {"id": "A02", "name": "李雷"},
            ],
            date="2024-02-03",
            year=2024,
            source={"name": "Journal of Representative Works"},
            doi="https://doi.org/10.1000/example",
            abstract={"text": ABSTRACT_SENTINEL, "reason": "rendered"},
            oa={"url": OTHER_SOURCE_SENTINEL, "license": OTHER_SOURCE_SENTINEL},
            openalex_url=OTHER_SOURCE_SENTINEL,
            raw=OTHER_SOURCE_SENTINEL,
        )
        # Sparse work: only the fields that cannot be absent.
        update_work(
            data, "W2",
            type="unmapped-work-type",
            title="A sparse work",
            authors=[],
            date=None,
            year=None,
            source={"name": None},
            doi=None,
            abstract={"text": ABSTRACT_SENTINEL, "reason": "rendered"},
            oa={"url": OTHER_SOURCE_SENTINEL, "license": None},
            openalex_url=OTHER_SOURCE_SENTINEL,
            raw=OTHER_SOURCE_SENTINEL,
        )

        render.DATA = data
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "synthetic render failed")

        citation_paths = {
            wid: render.SITE / "w" / wid / "citation.csl.json"
            for wid in ("W1", "W2")
        }
        for wid, path in citation_paths.items():
            bad += check(path.exists(), f"missing CSL-JSON artifact for {wid}")

        if all(path.exists() for path in citation_paths.values()):
            items = {
                wid: json.loads(path.read_text(encoding="utf-8"))
                for wid, path in citation_paths.items()
            }

            representative = items["W1"]
            bad += check(representative["id"] == "W1", "representative id was not passed through")
            bad += check(representative["type"] == "article-journal",
                         "representative type was not mapped to CSL vocabulary")
            bad += check(representative["title"] == "A representative work",
                         "representative title changed")
            bad += check(
                representative["author"] == [{"literal": "Zoë Ångström"}, {"literal": "李雷"}],
                "representative authors changed",
            )
            bad += check(representative["issued"] == {"date-parts": [[2024]]},
                         "representative issued date changed")
            bad += check(representative["container-title"] == "Journal of Representative Works",
                         "representative container-title changed")
            bad += check(representative["DOI"] == "https://doi.org/10.1000/example",
                         "representative DOI changed")
            bad += check("abstract" not in representative, "representative item carries an abstract field")

            sparse = items["W2"]
            bad += check(sparse["id"] == "W2", "sparse id was not passed through")
            bad += check(sparse["type"] == "document", "unmapped type did not fall back to document")
            bad += check(sparse["title"] == "A sparse work", "sparse title changed")
            bad += check(
                set(sparse) == {"id", "type", "title"},
                f"sparse item fabricated absent fields: {sorted(sparse)}",
            )
            bad += check("abstract" not in sparse, "sparse item carries an abstract field")

            for wid, path in citation_paths.items():
                raw_text = path.read_text(encoding="utf-8")
                bad += check(ABSTRACT_SENTINEL not in raw_text,
                             f"{wid} CSL-JSON artifact leaked the abstract sentinel")
                bad += check(OTHER_SOURCE_SENTINEL not in raw_text,
                             f"{wid} CSL-JSON artifact leaked an unrelated-source sentinel")

            bad += check(render.main() == 0, "second synthetic render failed")
            for wid, path in citation_paths.items():
                bad += check(
                    json.loads(path.read_text(encoding="utf-8")) == items[wid],
                    f"{wid} CSL-JSON is not deterministic across renders",
                )
    finally:
        (render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_csl_json_sentinels:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
