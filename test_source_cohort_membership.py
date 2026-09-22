#!/usr/bin/env python3
"""Direct coverage for source-disagreement cohort membership helpers."""
import sys

import quality
import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def work_with_verdict(field, verdict):
    return {"quality": {"evidence": [{"signal": f"{field}_source", "verdict": verdict}]}}


def assertion(source, value, raw):
    return {"source": source, "value": value, "raw": raw}


def main() -> int:
    bad = 0

    # Cohort configuration names every field/source combination, its route,
    # and labels which cohort-page renderers can use directly.
    expected_cohorts = {
        ("title", "crossref"): ("works/title-disagreement/crossref/", "Crossref", "Title"),
        ("title", "europepmc"): ("works/title-disagreement/europepmc/", "Europe PMC", "Title"),
        ("venue", "crossref"): ("works/venue-disagreement/crossref/", "Crossref", "Venue"),
        ("venue", "europepmc"): ("works/venue-disagreement/europepmc/", "Europe PMC", "Venue"),
        ("date", "crossref"): ("works/date-disagreement/crossref/", "Crossref", "Publication date"),
        ("date", "europepmc"): ("works/date-disagreement/europepmc/", "Europe PMC", "Publication date"),
    }
    bad += check(set(render.SOURCE_DISAGREEMENT_COHORTS) == set(expected_cohorts),
                 "source disagreement cohorts do not cover every field/source pair")
    for key, (path, source_label, field_label) in expected_cohorts.items():
        cohort = render.SOURCE_DISAGREEMENT_COHORTS.get(key, {})
        bad += check((cohort.get("path"), cohort.get("source_label"), cohort.get("field_label"))
                     == (path, source_label, field_label), f"{key} cohort route or labels are wrong")

    # `both_disagree` overlaps instead of choosing one source cohort.
    for field in ("title", "venue", "date"):
        both = work_with_verdict(field, quality.BOTH_DISAGREE)
        bad += check(render.source_verdict_for(both, field) == quality.BOTH_DISAGREE,
                     f"{field} did not read its quality-evidence verdict")
        for source in ("crossref", "europepmc"):
            bad += check(render.disagrees_with(both, field, source),
                         f"both_disagree omitted {field} from the {source} cohort")
        bad += check(render.is_comparable(both, field),
                     f"both_disagree is not comparable for {field}")

    # The only membership cases are source-specific disagreement verdicts.
    for field in ("title", "venue", "date"):
        crossref = work_with_verdict(field, quality.CROSSREF_DISAGREES)
        europepmc = work_with_verdict(field, quality.EUROPEPMC_DISAGREES)
        bad += check(render.disagrees_with(crossref, field, "crossref"),
                     f"crossref_disagrees missed the Crossref {field} cohort")
        bad += check(not render.disagrees_with(crossref, field, "europepmc"),
                     f"crossref_disagrees leaked into the Europe PMC {field} cohort")
        bad += check(render.disagrees_with(europepmc, field, "europepmc"),
                     f"europepmc_disagrees missed the Europe PMC {field} cohort")
        bad += check(not render.disagrees_with(europepmc, field, "crossref"),
                     f"europepmc_disagrees leaked into the Crossref {field} cohort")

    no_membership = (
        (work_with_verdict("title", quality.AGREE), "agree"),
        (work_with_verdict("title", quality.UNAVAILABLE), "unavailable"),
        (work_with_verdict("title", "not-a-verdict"), "unknown verdict"),
        ({"quality": {"evidence": [{"signal": "authors", "verdict": quality.BOTH_DISAGREE}]}},
         "unrelated evidence"),
        ({}, "missing quality"),
    )
    for work, label in no_membership:
        for source in ("crossref", "europepmc"):
            bad += check(not render.disagrees_with(work, "title", source),
                         f"{label} unexpectedly joined the {source} cohort")

    bad += check(not render.is_comparable(work_with_verdict("date", quality.UNAVAILABLE), "date"),
                 "unavailable verdict is comparable")
    bad += check(not render.is_comparable({}, "date"), "missing verdict is comparable")
    bad += check(render.is_comparable(work_with_verdict("date", quality.AGREE), "date"),
                 "agree verdict is not comparable")
    for verdict in (quality.CROSSREF_DISAGREES, quality.EUROPEPMC_DISAGREES, quality.BOTH_DISAGREE):
        bad += check(render.is_comparable(work_with_verdict("date", verdict), "date"),
                     f"{verdict} is not comparable")

    openalex_title = assertion("OpenAlex", "OpenAlex title", "sha-openalex-title")
    openalex_venue = assertion("OpenAlex", "OpenAlex venue", "sha-openalex-venue")
    openalex_date = assertion("OpenAlex", "2020-01-01", "sha-openalex-date")
    observations_work = {
        "source_comparison": {
            "title": {
                "openalex": openalex_title,
                "crossref": [
                    assertion("Crossref", "Crossref title one", "sha-crossref-title-1"),
                    assertion("Crossref", "Crossref title two", "sha-crossref-title-2"),
                ],
                "europepmc": [
                    assertion("Europe PMC", "Europe PMC title one", "sha-europepmc-title-1"),
                    assertion("Europe PMC", "Europe PMC title two", "sha-europepmc-title-2"),
                ],
            },
            "venue": {
                "openalex": openalex_venue,
                "crossref": [
                    assertion("Crossref", "Crossref venue one", "sha-crossref-venue-1"),
                    assertion("Crossref", "Crossref venue two", "sha-crossref-venue-2"),
                ],
            },
            "date": {
                "openalex": openalex_date,
                "crossref": [assertion("Crossref", "2020", "sha-crossref-date")],
                "europepmc": [
                    assertion("Europe PMC", "2020-01-01", "sha-europepmc-date-1"),
                    assertion("Europe PMC", "2020-01", "sha-europepmc-date-2"),
                ],
            },
        },
        "record_comparison": {
            "venue": {
                "openalex": assertion("openalex", "OpenAlex venue", "sha-record-openalex-venue"),
                "europepmc": assertion("europepmc", "Europe PMC venue", "sha-europepmc-venue"),
            },
        },
    }
    bad += check(render.source_observations(observations_work, "title", "crossref") == [
        openalex_title,
        *observations_work["source_comparison"]["title"]["crossref"],
    ], "title Crossref observations lost an assertion or its raw sha")
    bad += check(render.source_observations(observations_work, "date", "europepmc") == [
        openalex_date,
        *observations_work["source_comparison"]["date"]["europepmc"],
    ], "date Europe PMC observations lost an assertion or its raw sha")
    bad += check(render.source_observations(observations_work, "venue", "crossref") == [
        openalex_venue,
        *observations_work["source_comparison"]["venue"]["crossref"],
    ], "venue Crossref observations lost an assertion or its raw sha")
    bad += check(render.source_observations(observations_work, "venue", "europepmc") == [
        openalex_venue,
        observations_work["record_comparison"]["venue"]["europepmc"],
    ], "Europe PMC venue did not fall back to record_comparison")
    bad += check(render.source_observations(
        {"source_comparison": {"title": {"openalex": openalex_title}}}, "title", "crossref"
    ) == [openalex_title], "a field with no requested assertion did not retain OpenAlex alone")
    bad += check(render.source_observations(work_with_verdict("title", quality.AGREE), "title", "crossref") == [],
                 "a verdict without comparison data did not return gracefully")

    print("test_source_cohort_membership:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
