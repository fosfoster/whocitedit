#!/usr/bin/env python3
"""Offline rendering of the title/venue/date panel once Europe PMC is a third source.

Calls `render.record_comparison_html` directly with fabricated export blocks --
no database, no harvest -- because the question here is only what the panel
does with the block it is handed: a three-source work, a Crossref-only work, a
Europe-PMC-only work, and a block exported before Europe PMC or the venue
comparison existed, which is every work payload in the committed `web/data`.
"""
import re
import sys

import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


PAYLOADS = {
    "sha_openalex": {"fetched_at": "2026-02-01T00:00:00+00:00", "url": "file://openalex"},
    "sha_crossref": {"fetched_at": "2026-02-02T00:00:00+00:00", "url": "file://crossref"},
    "sha_europepmc": {"fetched_at": "2026-02-03T00:00:00+00:00", "url": "file://europepmc"},
}


def entry(source: str, value, raw: str) -> dict:
    """One exported source assertion, the shape `export_json._record_comparison` writes."""
    return {"source": source, "value": value, "raw": raw}


# Three sources, and the venue is where they part: OpenAlex and Crossref name
# the same journal, Europe PMC names another. The panel reports that, it does
# not pick a winner.
THREE_SOURCE = {
    "role": "Crossref and Europe PMC title/venue/date comparison against the OpenAlex work record",
    "title": {
        "openalex": entry("openalex", "Deep Learning & Cats", "sha_openalex"),
        "crossref": entry("crossref", "Deep Learning & Cats", "sha_crossref"),
        "europepmc": entry("europepmc", "Deep Learning & Cats", "sha_europepmc"),
        "status": "agree",
    },
    "venue": {
        "openalex": entry("openalex", "Journal of <Testing>", "sha_openalex"),
        "crossref": entry("crossref", "J. Test.", "sha_crossref"),
        "europepmc": entry("europepmc", "Europe PMC Journal of <Cats>", "sha_europepmc"),
        "status": "disagree",
    },
    "date": {
        "openalex": entry("openalex", "2024-02-03", "sha_openalex"),
        "crossref": entry("crossref", "2024-02-03", "sha_crossref"),
        "europepmc": entry("europepmc", "2024-02-04", "sha_europepmc"),
        "status": "disagree",
        "precision": "day",
    },
}

# Crossref only: exactly what a work covered by Crossref and not Europe PMC
# exports today, and it has to keep rendering as it did.
TWO_SOURCE = {
    "role": "Crossref title/venue/date comparison against the OpenAlex work record",
    "title": {
        "openalex": entry("openalex", "A Crossref-Covered Work", "sha_openalex"),
        "crossref": entry("crossref", "A Crossref-Covered Work", "sha_crossref"),
        "status": "agree",
    },
    "venue": {
        "openalex": entry("openalex", "Journal of Testing", "sha_openalex"),
        "crossref": entry("crossref", "J. Test.", "sha_crossref"),
        "status": "agree",
    },
    "date": {
        "openalex": entry("openalex", "2020-01-01", "sha_openalex"),
        "crossref": entry("crossref", None, "sha_crossref"),
        "status": "unavailable",
    },
}

# Europe PMC only: no Crossref envelope for this work at all, so the block
# carries no `crossref` key rather than one holding nulls.
EUROPEPMC_ONLY = {
    "role": "Europe PMC title/venue/date comparison against the OpenAlex work record",
    "title": {
        "openalex": entry("openalex", "A Europe PMC-Covered Work", "sha_openalex"),
        "europepmc": entry("europepmc", "A Europe PMC-Covered Work", "sha_europepmc"),
        "status": "agree",
    },
    "venue": {
        "openalex": entry("openalex", "Journal of Testing", "sha_openalex"),
        "europepmc": entry("europepmc", "Europe PMC Journal", "sha_europepmc"),
        "status": "disagree",
    },
    "date": {
        "openalex": entry("openalex", "2022-05-05", "sha_openalex"),
        "europepmc": entry("europepmc", "2022-05-05", "sha_europepmc"),
        "status": "agree",
    },
}

# A block exported before Europe PMC and the venue comparison existed: title
# and date only, no `venue` key, no `europepmc` entry anywhere. Every work
# payload in the committed `web/data` release is at most this until an
# operator re-exports, so this one must render rather than raise.
LEGACY = {
    "role": "Crossref title/date comparison against the OpenAlex work record",
    "title": {
        "openalex": entry("openalex", "A Legacy Payload Work", "sha_openalex"),
        "crossref": entry("crossref", "A Legacy Payload Work", "sha_crossref"),
        "status": "agree",
    },
    "date": {
        "openalex": entry("openalex", "2019-03-03", "sha_openalex"),
        "crossref": entry("crossref", "2019", "sha_crossref"),
        "status": "agree",
        "precision": "year",
    },
}


def section(panel: str, label: str) -> str:
    """The one field block whose row label is `label`, or "" when absent."""
    match = re.search(
        r'<li><span class="badge [^"]*">[^<]*</span> <span>%s</span>.*?</ul></li>' % re.escape(label),
        panel, re.S,
    )
    return match.group(0) if match else ""


def main() -> int:
    bad = 0

    # -- three sources ------------------------------------------------------
    panel = render.record_comparison_html(THREE_SOURCE, PAYLOADS)
    bad += check(panel.strip() != "", "a three-source comparison rendered no panel at all")

    # The panel says what it holds: title, venue and date, across the sources.
    bad += check("<h2>Title, venue and date across sources</h2>" in panel,
                 "the panel heading does not name title, venue and date")
    bad += check(THREE_SOURCE["role"][:1].upper() + THREE_SOURCE["role"][1:] in panel,
                 "the panel's meta sentence does not carry the exported role naming both extra sources")
    bad += check("stays as OpenAlex published it" in panel,
                 "the panel no longer promises the record above it is left alone")

    # All three sources are labelled, Europe PMC by the name render.py already
    # uses for it elsewhere.
    for label in ("OpenAlex", "Crossref", "Europe PMC"):
        bad += check(f"<b>{label}</b>:" in panel, f"the panel does not label the {label} assertion")
    bad += check(render.SOURCE_LABELS.get("europepmc") == "Europe PMC",
                 "SOURCE_LABELS does not spell europepmc the way CITATION_SOURCE_NAMES does")

    # Every field block -- title, venue and date -- carries its Europe PMC row.
    for label in ("Title", "Venue", "Publication date"):
        block = section(panel, label)
        bad += check(block != "", f"the panel has no {label} block")
        bad += check("<b>Europe PMC</b>:" in block,
                     f"the {label} block does not carry the Europe PMC assertion")

    # The Europe PMC value is shown as asserted (and HTML-escaped), beside its
    # own payload sha and its own fetch date -- not Crossref's.
    venue = section(panel, "Venue")
    bad += check("Europe PMC Journal of &lt;Cats&gt;" in venue,
                 "the Europe PMC venue value is missing or unescaped in the venue block")
    bad += check("Europe PMC Journal of <Cats>" not in venue,
                 "the Europe PMC venue value leaked unescaped markup")
    europepmc_row = re.search(r"<li><b>Europe PMC</b>:.*?</li>", venue, re.S)
    bad += check(europepmc_row is not None, "the venue block has no Europe PMC row")
    row = europepmc_row.group(0) if europepmc_row else ""
    bad += check("sha256 sha_europepmc" in row,
                 "the Europe PMC row does not name its own payload sha")
    bad += check("fetched 2026-02-03T00:00:00+00:00" in row,
                 "the Europe PMC row does not carry its own fetched date")
    bad += check("sha_crossref" not in row and "sha_openalex" not in row,
                 "the Europe PMC row carries another source's payload sha")

    # Each other source keeps its own sha and fetch date, as before.
    bad += check("sha256 sha_openalex" in venue and "fetched 2026-02-01T00:00:00+00:00" in venue,
                 "the OpenAlex venue row lost its own sha or fetched date")
    bad += check("sha256 sha_crossref" in venue and "fetched 2026-02-02T00:00:00+00:00" in venue,
                 "the Crossref venue row lost its own sha or fetched date")

    # The venue row's badge is the exported verdict, and the disagreement is
    # shown rather than resolved: OpenAlex still reads as OpenAlex published it.
    bad += check('<span class="badge disagree">disagree</span> <span>Venue</span>' in panel,
                 "the venue row does not emit its exported 'disagree' badge")
    bad += check('<span class="badge agree">agree</span> <span>Title</span>' in panel,
                 "the title row does not emit its exported 'agree' badge")
    bad += check("Journal of &lt;Testing&gt;" in venue,
                 "the OpenAlex venue value was corrected or dropped by the disagreement")
    bad += check("compared to the day" in section(panel, "Publication date"),
                 "the date block dropped its precision note")

    # Fixed order: OpenAlex, then Crossref, then Europe PMC.
    order = [m.group(1) for m in re.finditer(r"<li><b>([^<]+)</b>:", venue)]
    bad += check(order == ["OpenAlex", "Crossref", "Europe PMC"],
                 f"the venue rows are not in the fixed source order: {order}")

    # -- Crossref only: unchanged from before Europe PMC existed -------------
    two = render.record_comparison_html(TWO_SOURCE, PAYLOADS)
    bad += check("Europe PMC" not in two,
                 "a Crossref-only comparison rendered a Europe PMC row anyway")
    bad += check("sha_europepmc" not in two,
                 "a Crossref-only comparison named a Europe PMC payload")
    for label in ("OpenAlex", "Crossref"):
        bad += check(f"<b>{label}</b>:" in two, f"the Crossref-only panel does not label the {label} assertion")
    bad += check('<span class="badge unavailable">unavailable</span> <span>Publication date</span>' in two,
                 "the Crossref-only panel lost its date verdict")
    bad += check("not asserted" in two,
                 "the Crossref-only panel hides that Crossref asserted no date")
    bad += check(len(re.findall(r"<li><b>[^<]+</b>:", section(two, "Venue"))) == 2,
                 "the Crossref-only venue block does not hold exactly two source rows")

    # -- legacy: no venue block, no europepmc entries -----------------------
    try:
        legacy = render.record_comparison_html(LEGACY, PAYLOADS)
    except Exception as exc:  # a KeyError here is the regression this guards
        legacy = ""
        bad += check(False, f"a pre-Europe-PMC payload raised {exc!r} instead of rendering")
    bad += check("<span>Title</span>" in legacy and "<span>Publication date</span>" in legacy,
                 "the legacy payload lost the title and date blocks it renders today")
    bad += check("<span>Venue</span>" not in legacy,
                 "the legacy payload, which exported no venue block, rendered one anyway")
    bad += check("Europe PMC" not in legacy,
                 "the legacy payload rendered a Europe PMC row it never exported")
    bad += check("A Legacy Payload Work" in legacy and "sha256 sha_crossref" in legacy,
                 "the legacy payload's own values and payload shas went missing")
    bad += check("compared to the year" in legacy, "the legacy payload lost its date precision note")

    # -- Europe PMC only: no Crossref envelope for this work ----------------
    only = render.record_comparison_html(EUROPEPMC_ONLY, PAYLOADS)
    bad += check("<b>OpenAlex</b>:" in only and "<b>Europe PMC</b>:" in only,
                 "a Europe-PMC-only comparison does not name both OpenAlex and Europe PMC")
    bad += check("<b>Crossref</b>:" not in only,
                 "a Europe-PMC-only comparison invented a Crossref row")
    bad += check("Europe PMC Journal" in only,
                 "a Europe-PMC-only comparison does not show Europe PMC's asserted venue")
    bad += check("sha256 sha_europepmc" in only,
                 "a Europe-PMC-only comparison does not show the Europe PMC payload sha")
    bad += check('<span class="badge disagree">disagree</span> <span>Venue</span>' in only,
                 "a Europe-PMC-only venue disagreement does not emit its badge")

    # -- no comparison at all: every work in the committed web/data ---------
    bad += check(render.record_comparison_html(None, PAYLOADS) == "",
                 "a work with no record_comparison rendered a panel anyway")
    bad += check(render.record_comparison_html({}, PAYLOADS) == "",
                 "an empty record_comparison rendered a panel anyway")

    print("test_europepmc_comparison_render:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
