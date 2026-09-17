#!/usr/bin/env python3
"""Work-record quality. The signals are the ones actually found in the corpus,
so the cases here are the real records rather than invented ones -- and the
refusal to score citation counts gets a test too, because a documented refusal
that nothing enforces is just a comment."""
import sys

import quality as Q


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


# The two records that motivated this module, verbatim from the first harvest.
BAD_1 = dict(title="Exploiting Generative AI to Scale up Intelligent Tutoring Systems",
             doi="https://doi.org/10.4230/lipics.itp.2023.19", year=2023,
             n_authors=0, referenced_count=0, cited_by_count=79071)
BAD_2 = dict(title="AI-Assisted Pipeline for Dynamic Generation of Trustworthy Health Supplement Content at Scale",
             doi="https://doi.org/10.4230/lipics.cosit.2022.18", year=2018,
             n_authors=0, referenced_count=55, cited_by_count=46036)
GOOD = dict(title="Random Forests", doi="https://doi.org/10.1023/a:1010933404324",
            year=2001, n_authors=1, referenced_count=16, cited_by_count=131109)


def main() -> int:
    bad = 0

    bad += check(Q.doi_year("https://doi.org/10.4230/lipics.cosit.2022.18") == 2022, "doi year")
    bad += check(Q.doi_year("https://doi.org/10.1023/a:1010933404324") is None,
                 "a DOI with no year must not invent one")
    bad += check(Q.doi_year(None) is None, "None doi")
    bad += check(Q.doi_year("https://doi.org/10.1000/xyz") is None, "no year token")

    bad += check(Q.assess(**BAD_1)[0] == Q.SUSPECT, "the zero-author zero-reference record is not suspect")
    bad += check(Q.assess(**BAD_2)[0] == Q.SUSPECT, "the zero-author DOI-mismatch record is not suspect")
    bad += check(Q.assess(**GOOD)[0] == Q.COMPLETE, "a sound record was flagged")

    # THE DOCUMENTED REFUSAL. quality.py says a citation count is never itself a
    # signal, because this corpus is selected by citation count. This is the
    # test that would catch someone adding one.
    for cites in (1, 1_000, 500_000, 10_000_000):
        band, ev = Q.assess(**{**GOOD, "cited_by_count": cites})
        bad += check(band == Q.COMPLETE, f"{cites} citations alone changed the band to {band}")
    bad += check(
        not any(e["signal"] in ("citations", "citation_outlier") for e in Q.assess(**GOOD)[1]),
        "a citation-count signal appeared; the corpus is selected on that axis",
    )

    # source_verdict(): the fold from two Crossref/Europe-PMC statuses to one
    # three-way verdict that distinguishes which source, if either, disagrees.
    bad += check(Q.source_verdict("agree", "agree") == Q.AGREE, "three-way agreement was not AGREE")
    bad += check(Q.source_verdict("agree", None) == Q.AGREE, "crossref-only agreement was not AGREE")
    bad += check(Q.source_verdict(None, "agree") == Q.AGREE, "europepmc-only agreement was not AGREE")
    bad += check(Q.source_verdict("disagree", "agree") == Q.CROSSREF_DISAGREES,
                 "a lone Crossref disagreement was not CROSSREF_DISAGREES")
    bad += check(Q.source_verdict("agree", "disagree") == Q.EUROPEPMC_DISAGREES,
                 "a lone Europe PMC disagreement was not EUROPEPMC_DISAGREES")
    bad += check(Q.source_verdict("disagree", "disagree") == Q.BOTH_DISAGREE,
                 "two disagreeing sources was not BOTH_DISAGREE")
    bad += check(Q.source_verdict(None, None) == Q.UNAVAILABLE, "no comparable status was not UNAVAILABLE")
    bad += check(Q.source_verdict("unavailable", "incomparable") == Q.UNAVAILABLE,
                 "unavailable/incomparable statuses were not UNAVAILABLE")

    # A three-way agreement on venue/title/date stays COMPLETE.
    three_way_agree = Q.assess(
        **GOOD,
        venue_status="agree", venue_europepmc_status="agree",
        title_status="agree", title_europepmc_status="agree",
        date_status="agree", date_europepmc_status="agree",
    )
    bad += check(three_way_agree[0] == Q.COMPLETE, "three-way source agreement was not COMPLETE")
    for signal in ("venue_source", "title_source", "date_source"):
        entry = next(e for e in three_way_agree[1] if e["signal"] == signal)
        bad += check(entry["verdict"] == Q.AGREE, f"{signal} three-way agreement did not report AGREE")
        bad += check(entry["direction"] == "supports", f"{signal} three-way agreement did not support")

    # A Europe-PMC-only disagreement on venue weakens the band and is
    # distinguishable from a Crossref-only disagreement on the same field.
    epmc_only = Q.assess(**GOOD, venue_status="agree", venue_europepmc_status="disagree")
    bad += check(epmc_only[0] == Q.PARTIAL, "a Europe-PMC-only venue disagreement did not weaken the band")
    epmc_entry = next(e for e in epmc_only[1] if e["signal"] == "venue_source")
    bad += check(epmc_entry["verdict"] == Q.EUROPEPMC_DISAGREES,
                 "a Europe-PMC-only venue disagreement did not report europepmc_disagrees")
    bad += check(epmc_entry["direction"] == "weakens", "a Europe-PMC-only venue disagreement did not weaken")

    crossref_only = Q.assess(**GOOD, venue_status="disagree", venue_europepmc_status="agree")
    bad += check(crossref_only[0] == Q.PARTIAL, "a Crossref-only venue disagreement did not weaken the band")
    crossref_entry = next(e for e in crossref_only[1] if e["signal"] == "venue_source")
    bad += check(crossref_entry["verdict"] == Q.CROSSREF_DISAGREES,
                 "a Crossref-only venue disagreement did not report crossref_disagrees")
    bad += check(crossref_entry["verdict"] != epmc_entry["verdict"],
                 "a Crossref-only and Europe-PMC-only disagreement reported the same verdict")

    both_disagree = Q.assess(**GOOD, venue_status="disagree", venue_europepmc_status="disagree")
    bad += check(both_disagree[0] == Q.PARTIAL, "two disagreeing sources on one field did not weaken the band")
    both_entry = next(e for e in both_disagree[1] if e["signal"] == "venue_source")
    bad += check(both_entry["verdict"] == Q.BOTH_DISAGREE,
                 "two disagreeing venue sources did not report both_disagree")

    # Title and date behave the same way as venue.
    for signal, status_kw, epmc_kw in (
        ("title_source", "title_status", "title_europepmc_status"),
        ("date_source", "date_status", "date_europepmc_status"),
    ):
        epmc_case = Q.assess(**GOOD, **{status_kw: "agree", epmc_kw: "disagree"})
        bad += check(epmc_case[0] == Q.PARTIAL, f"a Europe-PMC-only {signal} disagreement did not weaken the band")
        entry = next(e for e in epmc_case[1] if e["signal"] == signal)
        bad += check(entry["verdict"] == Q.EUROPEPMC_DISAGREES, f"{signal} did not report europepmc_disagrees")

        crossref_case = Q.assess(**GOOD, **{status_kw: "disagree", epmc_kw: "agree"})
        entry = next(e for e in crossref_case[1] if e["signal"] == signal)
        bad += check(entry["verdict"] == Q.CROSSREF_DISAGREES, f"{signal} did not report crossref_disagrees")

    # A year apart is ordinary -- online-first in December, issue in January.
    near = Q.assess(**{**GOOD, "doi": "https://doi.org/10.1023/proc.2002.4", "year": 2001})
    bad += check(near[0] == Q.COMPLETE, f"a one-year DOI gap was flagged: {near[0]}")
    far = Q.assess(**{**GOOD, "doi": "https://doi.org/10.1023/proc.2015.4", "year": 2001})
    bad += check(far[0] == Q.PARTIAL, f"a fourteen-year DOI gap was not flagged: {far[0]}")

    # A thin record with few citations is unremarkable; the same record with a
    # huge citation count is incomplete rather than austere.
    quiet = Q.assess(**{**GOOD, "referenced_count": 0, "cited_by_count": 3})
    loud = Q.assess(**{**GOOD, "referenced_count": 0, "cited_by_count": 50_000})
    bad += check(quiet[0] == Q.COMPLETE, "a lightly cited record with no references was flagged")
    bad += check(loud[0] == Q.PARTIAL, "a heavily cited record with no references was not flagged")

    # Our own missing-title substitute must still read as a missing title.
    sub = Q.assess(**{**GOOD, "title": "[No title in the source record — Somewhere]"})
    bad += check(sub[0] == Q.PARTIAL, "the substituted title masked the gap it stands in for")

    # Every direction a signal can emit needs a template, or the page renders a
    # raw value at a reader. This includes every three-way verdict a
    # title/date/venue signal can fold to (agree, crossref_disagrees,
    # europepmc_disagrees, both_disagree, unavailable) and the plain two-way
    # work_type_status.
    seen: dict[str, set] = {}
    cases = (
        GOOD, BAD_1, BAD_2, {**GOOD, "doi": None}, sub and {**GOOD, "title": ""},
        {**GOOD, "work_type_status": "agree"},
        {**GOOD, "work_type_status": "disagree"},
        {**GOOD, "work_type_status": "unavailable"},
        {**GOOD, "venue_status": "agree", "venue_europepmc_status": "agree"},
        {**GOOD, "venue_status": "disagree", "venue_europepmc_status": "agree"},
        {**GOOD, "venue_status": "agree", "venue_europepmc_status": "disagree"},
        {**GOOD, "venue_status": "disagree", "venue_europepmc_status": "disagree"},
        {**GOOD, "title_status": "agree", "title_europepmc_status": "agree"},
        {**GOOD, "title_status": "disagree", "title_europepmc_status": "agree"},
        {**GOOD, "title_status": "agree", "title_europepmc_status": "disagree"},
        {**GOOD, "title_status": "disagree", "title_europepmc_status": "disagree"},
        {**GOOD, "date_status": "agree", "date_europepmc_status": "agree"},
        {**GOOD, "date_status": "disagree", "date_europepmc_status": "agree"},
        {**GOOD, "date_status": "agree", "date_europepmc_status": "disagree"},
        {**GOOD, "date_status": "disagree", "date_europepmc_status": "disagree"},
    )
    for case in cases:
        for item in Q.assess(**case)[1]:
            seen.setdefault(item["signal"], set()).add(item["direction"])
    for signal, directions in seen.items():
        bad += check(signal in Q.NOTE_TEMPLATES, f"no templates for signal {signal}")
        for d in directions:
            bad += check(d in Q.NOTE_TEMPLATES.get(signal, {}), f"no template for {signal}/{d}")

    # The bands say what the product promises. `suspect` in particular has to
    # tell the reader the record is unaltered, or the flag reads as a deletion.
    for b in (Q.COMPLETE, Q.PARTIAL, Q.SUSPECT):
        bad += check(bool(Q.band_sentence(b)), f"no sentence for {b}")
    bad += check("unaltered" in Q.band_sentence(Q.SUSPECT),
                 "the suspect band does not say the record is shown unaltered")

    bad += check(Q.decode_evidence(Q.encode_evidence(Q.assess(**BAD_1)[1])) == Q.assess(**BAD_1)[1],
                 "evidence does not round-trip")

    print("test_quality:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
