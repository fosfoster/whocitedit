#!/usr/bin/env python3
"""Quality evidence must retain the source named by its verdict."""
import html
import sys

import identity as I
import quality as Q
import render


VERDICTS = (
    (Q.AGREE, "supports"),
    (Q.CROSSREF_DISAGREES, "weakens"),
    (Q.EUROPEPMC_DISAGREES, "weakens"),
    (Q.BOTH_DISAGREE, "weakens"),
    (Q.UNAVAILABLE, "neutral"),
)


# Keep these promises independent of NOTE_TEMPLATES: this is the exact text a
# reader must get for each source/field verdict, rather than a test of the
# template dictionary alone.
EXPECTED = {
    "title_source": {
        Q.AGREE: "The sources agree about this work's title.",
        Q.CROSSREF_DISAGREES: "Crossref disagrees with OpenAlex about this work's title. Each is shown as a parallel observation; none is corrected here.",
        Q.EUROPEPMC_DISAGREES: "Europe PMC disagrees with OpenAlex about this work's title. Each is shown as a parallel observation; none is corrected here.",
        Q.BOTH_DISAGREE: "Both Crossref and Europe PMC disagree with OpenAlex about this work's title. Each is shown as a parallel observation; none is corrected here.",
        Q.UNAVAILABLE: "No comparable source assertion is available for this work's title.",
    },
    "venue_source": {
        Q.AGREE: "The sources agree about this work's venue.",
        Q.CROSSREF_DISAGREES: "Crossref disagrees with OpenAlex about this work's venue. Each is shown as a parallel observation; none is corrected here.",
        Q.EUROPEPMC_DISAGREES: "Europe PMC disagrees with OpenAlex about this work's venue. Each is shown as a parallel observation; none is corrected here.",
        Q.BOTH_DISAGREE: "Both Crossref and Europe PMC disagree with OpenAlex about this work's venue. Each is shown as a parallel observation; none is corrected here.",
        Q.UNAVAILABLE: "No comparable source assertion is available for this work's venue.",
    },
    "date_source": {
        Q.AGREE: "The sources agree about this work's publication date.",
        Q.CROSSREF_DISAGREES: "Crossref disagrees with OpenAlex about this work's publication date. Each is shown as a parallel observation; none is corrected here.",
        Q.EUROPEPMC_DISAGREES: "Europe PMC disagrees with OpenAlex about this work's publication date. Each is shown as a parallel observation; none is corrected here.",
        Q.BOTH_DISAGREE: "Both Crossref and Europe PMC disagree with OpenAlex about this work's publication date. Each is shown as a parallel observation; none is corrected here.",
        Q.UNAVAILABLE: "No comparable source assertion is available for this work's publication date.",
    },
}


def check(condition, message):
    if condition:
        return 0
    print(f"  FAIL: {message}")
    return 1


def expected_html(rows):
    return '<ul class="evidence">' + "".join(
        f'<li><span class="dir {direction}">{direction}</span>'
        f'<span>{html.escape(EXPECTED[signal][verdict], quote=True)}</span></li>'
        for signal, verdict, direction in rows
    ) + "</ul>"


def main() -> int:
    rows = [
        (signal, verdict, direction)
        for signal in ("title_source", "venue_source", "date_source")
        for verdict, direction in VERDICTS
    ]
    evidence = [
        {"signal": signal, "verdict": verdict, "direction": direction, "value": "disagree"}
        for signal, verdict, direction in rows
    ]

    bad = check(len(rows) == 15, "the title/venue/date verdict matrix is incomplete")
    bad += check(
        render.evidence_html(evidence, Q.NOTE_TEMPLATES) == expected_html(rows),
        "the complete source-verdict matrix did not render its exact reader-facing text",
    )

    # Pre-verdict evidence (including author and identity evidence) must retain
    # its direction template.
    no_verdict = [
        {"signal": "authors", "direction": "supports", "value": 2},
        {"signal": "orcid", "direction": "neutral", "value": None},
    ]
    bad += check(
        render.evidence_html(no_verdict, {**Q.NOTE_TEMPLATES, **I.NOTE_TEMPLATES})
        == '<ul class="evidence"><li><span class="dir supports">supports</span>'
           '<span>2 author record(s) attached.</span></li>'
           '<li><span class="dir neutral">neutral</span>'
           '<span>No ORCID on this record, so its identity rests on inference alone.</span></li></ul>',
        "evidence without a verdict did not fall back to its direction template",
    )

    # Older note sets have only direction keys for a source signal. An unknown
    # verdict must use that stable copy instead of exposing signal/value text.
    legacy_notes = {"title_source": {"weakens": "Legacy title disagreement."}}
    legacy_evidence = [{
        "signal": "title_source",
        "verdict": Q.EUROPEPMC_DISAGREES,
        "direction": "weakens",
        "value": "disagree",
    }]
    bad += check(
        render.evidence_html(legacy_evidence, legacy_notes)
        == '<ul class="evidence"><li><span class="dir weakens">weakens</span>'
           '<span>Legacy title disagreement.</span></li></ul>',
        "notes without verdict-specific copy did not fall back to their direction template",
    )

    print("test_quality_evidence_render:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
