#!/usr/bin/env python3
"""Offline coverage for the static CSL-JSON artifact beside every rendered work page."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import export_json
import render
import test_entity_export


ABSTRACT_SENTINEL = "CSL_ABSTRACT_MUST_NOT_APPEAR"
OTHER_SOURCE_SENTINEL = "CSL_OTHER_SOURCE_MUST_NOT_APPEAR"

# The `type` enum of the CSL-JSON input schema (csl-data.json). Every exported
# work type has to land on one of these, or a validating importer rejects the file.
CSL_TYPE_ENUM = {
    "article", "article-journal", "article-magazine", "article-newspaper", "bill",
    "book", "broadcast", "chapter", "classic", "collection", "dataset", "document",
    "entry", "entry-dictionary", "entry-encyclopedia", "event", "figure", "graphic",
    "hearing", "interview", "legal_case", "legislation", "manuscript", "map",
    "motion_picture", "musical_score", "pamphlet", "paper-conference", "patent",
    "performance", "periodical", "personal_communication", "post", "post-weblog",
    "regulation", "report", "review", "review-book", "software", "song", "speech",
    "standard", "thesis", "treaty", "webpage",
}

# The closest CSL type for each work type the export currently carries.
EXPECTED_TYPES = {
    "article": "article-journal",
    "book": "book",
    "book-chapter": "chapter",
    "book-review": "review-book",
    "conference-abstract": "paper-conference",
    "conference-paper": "paper-conference",
    "data-paper": "article-journal",
    "dataset": "dataset",
    "dissertation": "thesis",
    "editorial": "article-journal",
    "erratum": "article-journal",
    "other": "document",
    "paratext": "document",
    "preprint": "article",
    "reference-entry": "entry",
    "report": "report",
    "review": "article-journal",
    "software": "software",
    "software-paper": "article-journal",
}

ITEM_KEYS = {"id", "type", "title", "author", "issued", "container-title", "DOI"}
WORK_ARTIFACTS = {"index.html", "citation.bib", "citation.ris", "citation.csl.json"}

TITLE = 'A "quoted" title\nwith a line break \\ — Δ'
EXPECTED_REPRESENTATIVE = (
    "[\n"
    "  {\n"
    '    "id": "W1",\n'
    '    "type": "paper-conference",\n'
    '    "title": "A \\"quoted\\" title\\nwith a line break \\\\ — Δ",\n'
    '    "author": [\n'
    "      {\n"
    '        "literal": "Zoë Ångström"\n'
    "      },\n"
    "      {\n"
    '        "literal": "李雷"\n'
    "      }\n"
    "    ],\n"
    '    "issued": {\n'
    '      "date-parts": [\n'
    "        [\n"
    "          2024,\n"
    "          2,\n"
    "          3\n"
    "        ]\n"
    "      ]\n"
    "    },\n"
    '    "container-title": "Journal of Synthetic Science",\n'
    '    "DOI": "10.1000/Example.2024"\n'
    "  }\n"
    "]\n"
)
EXPECTED_SPARSE = (
    "[\n"
    "  {\n"
    '    "id": "W2",\n'
    '    "type": "document",\n'
    '    "title": "No optional metadata"\n'
    "  }\n"
    "]\n"
)
EXPECTED_YEAR_ONLY = (
    "[\n"
    "  {\n"
    '    "id": "W3",\n'
    '    "type": "book",\n'
    '    "title": "A book without a date",\n'
    '    "author": [\n'
    "      {\n"
    '        "literal": "Ada Lovelace"\n'
    "      }\n"
    "    ],\n"
    '    "issued": {\n'
    '      "date-parts": [\n'
    "        [\n"
    "          1843\n"
    "        ]\n"
    "      ]\n"
    "    },\n"
    '    "container-title": "Analytical Engine Press"\n'
    "  }\n"
    "]\n"
)

REPRESENTATIVE = {
    "id": "W1",
    "type": "conference-paper",
    "title": TITLE,
    "authors": [{"id": "A01", "name": "Zoë Ångström"}, {"id": "A02", "name": "李雷"}],
    "date": "2024-02-03",
    "year": 2024,
    "source": {"id": OTHER_SOURCE_SENTINEL, "name": "Journal of Synthetic Science"},
    "doi": "https://doi.org/10.1000/Example.2024",
    "abstract": {"text": ABSTRACT_SENTINEL, "reason": "rendered"},
    "oa": {"is_oa": True, "status": "gold", "url": OTHER_SOURCE_SENTINEL, "license": "cc-by"},
    "openalex_url": OTHER_SOURCE_SENTINEL,
}
SPARSE = {
    "id": "W2",
    "type": "unmapped-work-type",
    "title": "No optional metadata",
    "authors": [],
    "date": None,
    "year": None,
    "source": {"id": None, "name": None},
    "doi": None,
    "abstract": {"text": ABSTRACT_SENTINEL, "reason": "rendered"},
    "oa": {"is_oa": False, "status": "closed", "url": None, "license": None},
}
YEAR_ONLY = {
    "id": "W3",
    "type": "book",
    "title": "A book without a date",
    "authors": [{"id": "A01", "name": "Ada Lovelace"}],
    "date": None,
    "year": 1843,
    "source": {"id": None, "name": "Analytical Engine Press"},
    "doi": None,
    "abstract": {"text": ABSTRACT_SENTINEL, "reason": "rendered"},
}


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def item_of(text: str, label: str) -> tuple[dict | None, int]:
    """Parse one artifact and hold it to the schema shape the ticket allows."""
    bad = 0
    try:
        parsed = json.loads(text)
    except ValueError:
        return None, check(False, f"{label} is not JSON")
    bad += check(isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict),
                 f"{label} is not a one-item CSL-JSON array")
    if bad:
        return None, bad
    item = parsed[0]
    bad += check(set(item) <= ITEM_KEYS, f"{label} uses fields outside the allowed set: {sorted(item)}")
    bad += check(isinstance(item.get("id"), str) and item["id"], f"{label} has no string id")
    bad += check(item.get("type") in CSL_TYPE_ENUM, f"{label} type {item.get('type')!r} is not a CSL type")
    for name in ("title", "container-title", "DOI"):
        if name in item:
            bad += check(isinstance(item[name], str) and item[name], f"{label} {name} is not a non-empty string")
    if "author" in item:
        bad += check(
            isinstance(item["author"], list) and item["author"]
            and all(set(a) == {"literal"} and isinstance(a["literal"], str) and a["literal"]
                    for a in item["author"]),
            f"{label} authors are not literal names",
        )
    if "issued" in item:
        parts = item["issued"].get("date-parts") if isinstance(item["issued"], dict) else None
        bad += check(
            set(item["issued"]) == {"date-parts"} and isinstance(parts, list) and len(parts) == 1
            and 1 <= len(parts[0]) <= 3
            and all(isinstance(p, int) and not isinstance(p, bool) for p in parts[0]),
            f"{label} issued is not one numeric date-parts entry",
        )
    return item, bad


def update_work(data: Path, wid: str, **changes) -> None:
    for path in (data / "works").glob("*.json"):
        payload = json.loads(path.read_text())
        if wid in payload:
            payload[wid].update(changes)
            path.write_text(json.dumps(payload, sort_keys=True))
            return
    raise KeyError(wid)


def serializer_checks() -> int:
    bad = 0
    representative = render.render_csl_json(REPRESENTATIVE)
    bad += check(representative == EXPECTED_REPRESENTATIVE,
                 "representative CSL-JSON lost field order, UTF-8, or JSON escaping")
    bad += check(render.render_csl_json(SPARSE) == EXPECTED_SPARSE,
                 "sparse work did not omit absent fields or fall back to document")
    bad += check(render.render_csl_json(YEAR_ONLY) == EXPECTED_YEAR_ONLY,
                 "year-only work did not fall back to a year date-part")
    empty = render.render_csl_json({"id": "W-empty", "title": None, "year": None, "date": None,
                                    "source": {}, "doi": None, "authors": [],
                                    "abstract": {"text": ABSTRACT_SENTINEL}})
    bad += check(empty == '[\n  {\n    "id": "W-empty",\n    "type": "document"\n  }\n]\n',
                 "a work with no optional metadata emitted more than id and type")
    for text in (representative, render.render_csl_json(SPARSE), empty):
        bad += check(ABSTRACT_SENTINEL not in text, "abstract entered the CSL-JSON serializer")
        bad += check(OTHER_SOURCE_SENTINEL not in text,
                     "a field outside the rendered citation sources entered the CSL-JSON serializer")
        _, shape_bad = item_of(text, "serializer output")
        bad += shape_bad
    bad += check(render.render_csl_json(REPRESENTATIVE) == representative,
                 "CSL-JSON serialization is not byte-stable")

    for work_type, csl_type in EXPECTED_TYPES.items():
        got = json.loads(render.render_csl_json({"id": "W", "type": work_type}))[0]["type"]
        bad += check(got == csl_type, f"{work_type} mapped to {got!r}, expected {csl_type!r}")
    bad += check(set(EXPECTED_TYPES.values()) <= CSL_TYPE_ENUM, "an expected CSL type is not in the schema enum")
    for work_type in ("unmapped-work-type", None, ""):
        got = json.loads(render.render_csl_json({"id": "W", "type": work_type}))[0]["type"]
        bad += check(got == "document", f"unknown type {work_type!r} did not fall back to document")

    for doi, expected in (
        ("https://doi.org/10.1000/a_b", "10.1000/a_b"),
        ("http://dx.doi.org/10.1000/x", "10.1000/x"),
        ("HTTPS://DOI.ORG/10.1000/Upper", "10.1000/Upper"),
        ("doi:10.1000/prefixed", "10.1000/prefixed"),
        ("10.1000/already-bare", "10.1000/already-bare"),
    ):
        got = json.loads(render.render_csl_json({"id": "W", "doi": doi}))[0].get("DOI")
        bad += check(got == expected, f"doi {doi!r} became {got!r}, expected {expected!r}")
    bad += check("DOI" not in json.loads(render.render_csl_json({"id": "W", "doi": None}))[0],
                 "an absent DOI was emitted")

    for date, year, expected in (
        ("2024-02-03", 2024, [[2024, 2, 3]]),
        ("2024-02-03", None, [[2024, 2, 3]]),
        ("2024-02", 2024, [[2024, 2]]),
        (None, 1843, [[1843]]),
        ("n.d.", 1843, [[1843]]),
        ("", 1843, [[1843]]),
    ):
        got = json.loads(render.render_csl_json({"id": "W", "date": date, "year": year}))[0].get("issued")
        bad += check(got == {"date-parts": expected},
                     f"date {date!r} with year {year!r} became {got!r}, expected {expected!r}")
    for date, year in ((None, None), ("", None), ("n.d.", None)):
        got = json.loads(render.render_csl_json({"id": "W", "date": date, "year": year}))[0]
        bad += check("issued" not in got, f"date {date!r} with year {year!r} fabricated an issued date")
    return bad


def render_checks() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
             render.DATA, render.SITE, render.ASSETS)
    try:
        db_path, _, _ = test_entity_export.build_corpus(tmp)
        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "synthetic export failed")

        data = tmp / "data"
        for fixture in (REPRESENTATIVE, SPARSE, YEAR_ONLY):
            update_work(data, fixture["id"], **{k: v for k, v in fixture.items() if k != "id"})
        works = {}
        for shard in (data / "works").glob("*.json"):
            works.update(json.loads(shard.read_text()))
        bad += check(set(works) == {"W1", "W2", "W3"}, "fixture corpus does not hold exactly W1-W3")

        render.DATA = data
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "synthetic render failed")
        site = render.SITE

        expected_paths = {site / "w" / wid / "citation.csl.json" for wid in works}
        bad += check(set(site.rglob("*.csl.json")) == expected_paths,
                     "not exactly one CSL-JSON artifact was emitted per work")
        for wid in works:
            names = {p.name for p in (site / "w" / wid).iterdir()}
            bad += check(names == WORK_ARTIFACTS, f"{wid} has extra or missing work artifacts: {sorted(names)}")

        first = {}
        for wid, work in works.items():
            path = site / "w" / wid / "citation.csl.json"
            if not path.exists():
                bad += check(False, f"missing CSL-JSON artifact for {wid}")
                continue
            raw = path.read_bytes()
            first[wid] = raw
            bad += check(not raw.startswith(b"\xef\xbb\xbf"), f"{wid} artifact starts with a BOM")
            try:
                text = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                bad += check(False, f"{wid} artifact is not valid UTF-8")
                continue
            bad += check(text == render.render_csl_json(work), f"{wid} artifact differs from its page data")
            bad += check(ABSTRACT_SENTINEL not in text, f"{wid} artifact leaked an abstract")
            bad += check(OTHER_SOURCE_SENTINEL not in text, f"{wid} artifact leaked an unrelated source field")
            _, shape_bad = item_of(text, f"{wid} artifact")
            bad += shape_bad

        if set(first) == set(works):
            representative = first["W1"].decode()
            bad += check(representative == EXPECTED_REPRESENTATIVE, "representative rendered artifact changed")
            bad += check("Zoë Ångström" in representative and "李雷" in representative,
                         "non-ASCII names were escaped instead of written as UTF-8")
            bad += check([a["literal"] for a in json.loads(representative)[0]["author"]]
                         == ["Zoë Ångström", "李雷"], "UTF-8 names do not round-trip through the artifact")
            bad += check(first["W2"].decode() == EXPECTED_SPARSE, "sparse rendered artifact fabricated absent fields")
            bad += check(first["W3"].decode() == EXPECTED_YEAR_ONLY, "year-only rendered artifact changed")

            bad += check(render.main() == 0, "second synthetic render failed")
            for wid, raw in first.items():
                bad += check((site / "w" / wid / "citation.csl.json").read_bytes() == raw,
                             f"{wid} CSL-JSON bytes are not deterministic across renders")
    finally:
        (export_json.OUT, export_json.DB_PATH, export_json.ROOT,
         render.DATA, render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)
    return bad


def main() -> int:
    bad = serializer_checks() + render_checks()
    print("test_csl_json:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
