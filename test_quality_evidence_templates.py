#!/usr/bin/env python3
"""Source-quality verdicts must select field- and source-specific evidence."""
import sys

import quality as Q


GOOD = dict(
    title="Random Forests",
    doi="https://doi.org/10.1023/a:1010933404324",
    year=2001,
    n_authors=1,
    referenced_count=16,
    cited_by_count=131109,
)


# Each row deliberately names the expected sentence rather than deriving it
# from the implementation: these are the reader-facing promises this test
# protects.
CASES = (
    ("title_source", "title_status", "title_europepmc_status", "agree", None, Q.AGREE,
     "The sources agree about this work's title."),
    ("title_source", "title_status", "title_europepmc_status", None, None, Q.UNAVAILABLE,
     "No comparable source assertion is available for this work's title."),
    ("title_source", "title_status", "title_europepmc_status", "disagree", "agree", Q.CROSSREF_DISAGREES,
     "Crossref disagrees with OpenAlex about this work's title. Each is shown as a parallel observation; none is corrected here."),
    ("title_source", "title_status", "title_europepmc_status", "agree", "disagree", Q.EUROPEPMC_DISAGREES,
     "Europe PMC disagrees with OpenAlex about this work's title. Each is shown as a parallel observation; none is corrected here."),
    ("title_source", "title_status", "title_europepmc_status", "disagree", "disagree", Q.BOTH_DISAGREE,
     "Both Crossref and Europe PMC disagree with OpenAlex about this work's title. Each is shown as a parallel observation; none is corrected here."),
    ("venue_source", "venue_status", "venue_europepmc_status", "agree", None, Q.AGREE,
     "The sources agree about this work's venue."),
    ("venue_source", "venue_status", "venue_europepmc_status", None, None, Q.UNAVAILABLE,
     "No comparable source assertion is available for this work's venue."),
    ("venue_source", "venue_status", "venue_europepmc_status", "disagree", "agree", Q.CROSSREF_DISAGREES,
     "Crossref disagrees with OpenAlex about this work's venue. Each is shown as a parallel observation; none is corrected here."),
    ("venue_source", "venue_status", "venue_europepmc_status", "agree", "disagree", Q.EUROPEPMC_DISAGREES,
     "Europe PMC disagrees with OpenAlex about this work's venue. Each is shown as a parallel observation; none is corrected here."),
    ("venue_source", "venue_status", "venue_europepmc_status", "disagree", "disagree", Q.BOTH_DISAGREE,
     "Both Crossref and Europe PMC disagree with OpenAlex about this work's venue. Each is shown as a parallel observation; none is corrected here."),
    ("date_source", "date_status", "date_europepmc_status", "agree", None, Q.AGREE,
     "The sources agree about this work's publication date."),
    ("date_source", "date_status", "date_europepmc_status", None, None, Q.UNAVAILABLE,
     "No comparable source assertion is available for this work's publication date."),
    ("date_source", "date_status", "date_europepmc_status", "disagree", "agree", Q.CROSSREF_DISAGREES,
     "Crossref disagrees with OpenAlex about this work's publication date. Each is shown as a parallel observation; none is corrected here."),
    ("date_source", "date_status", "date_europepmc_status", "agree", "disagree", Q.EUROPEPMC_DISAGREES,
     "Europe PMC disagrees with OpenAlex about this work's publication date. Each is shown as a parallel observation; none is corrected here."),
    ("date_source", "date_status", "date_europepmc_status", "disagree", "disagree", Q.BOTH_DISAGREE,
     "Both Crossref and Europe PMC disagree with OpenAlex about this work's publication date. Each is shown as a parallel observation; none is corrected here."),
)


def check(condition, message):
    if condition:
        return 0
    print(f"  FAIL: {message}")
    return 1


def main() -> int:
    bad = check(len(CASES) == 15, "the matrix does not cover all 15 field/verdict combinations")
    for signal, status_kw, europepmc_kw, status, europepmc_status, verdict, expected in CASES:
        _, evidence = Q.assess(**GOOD, **{status_kw: status, europepmc_kw: europepmc_status})
        item = next(entry for entry in evidence if entry["signal"] == signal)
        bad += check(item["verdict"] == verdict, f"{signal}/{verdict} emitted {item['verdict']!r}")
        template = Q.NOTE_TEMPLATES[signal].get(item["verdict"])
        bad += check(template == expected, f"{signal}/{verdict} template was {template!r}")

    for signal in ("title_source", "venue_source", "date_source"):
        bad += check(
            {"weakens", "supports", "neutral"} <= set(Q.NOTE_TEMPLATES[signal]),
            f"{signal} lost its direction-keyed compatibility templates",
        )

    print("test_quality_evidence_templates:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
