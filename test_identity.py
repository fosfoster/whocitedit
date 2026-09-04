#!/usr/bin/env python3
"""Identity confidence. The product promise is that nothing is merged and that a
doubtful record says so, so the tests are about what the band REFUSES to do as
much as what it reports."""
import sys

import identity as I


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def main() -> int:
    bad = 0

    # A spelled-out given name and its initial are the same person far more often
    # than not. If this collapsed wrongly, every well-cited author would score as
    # a merge risk and the band would be useless.
    bad += check(I.initials_form("Geoffrey E. Hinton") == I.initials_form("G. E. Hinton"),
                 "initials form did not collapse")
    bad += check(I.initials_form("Yann LeCun") != I.initials_form("Yoshua Bengio"),
                 "different people collapsed together")
    bad += check(I.normalize_name("O'Brien, P.") == "obrien p", f"normalize: {I.normalize_name(chr(79)+chr(39)+'Brien, P.')!r}")

    clean = dict(
        orcid="0000-0002-1825-0097",
        raw_names=["Ada Lovelace", "A. Lovelace"],
        institution_years=[("I1", 2018), ("I1", 2020), ("I2", 2022)],
        topic_fields=["CS", "CS", "CS", "Math"],
        works_in_corpus=4,
    )
    band, ev = I.assess(**clean)
    bad += check(band == I.HIGH, f"clean ORCID record should be high, got {band}")
    bad += check(all("note" not in e for e in ev),
                 "evidence carries prose; it must ship as data with templates in corpus.json")
    bad += check({e["signal"] for e in ev} == set(I.NOTE_TEMPLATES),
                 "a signal has no note template, so the page would render a raw value")
    for e in ev:
        bad += check(e["direction"] in I.NOTE_TEMPLATES[e["signal"]],
                     f"no template for {e['signal']}/{e['direction']}")

    # Two people sharing a name: many name forms, impossible mobility, no field
    # coherence. This must land LOW -- and must still return a record.
    band, _ = I.assess(
        orcid=None,
        raw_names=["J Smith", "John Smith", "Jonathan A Smith", "J-P Smith"],
        institution_years=[(f"I{i}", 2020) for i in range(9)],
        topic_fields=["A", "B", "C", "D", "E"],
        works_in_corpus=5,
    )
    bad += check(band == I.LOW, f"merge-shaped record should be low, got {band}")

    # Every band has a sentence, and the sentence is defined once.
    for b in (I.HIGH, I.MEDIUM, I.LOW):
        bad += check(bool(I.band_sentence(b)), f"no sentence for {b}")
    bad += check(I.band_sentence(I.LOW) is I.BAND_SENTENCES[I.LOW], "band sentence duplicated")
    bad += check("more than one person" in I.band_sentence(I.LOW),
                 "the low band must say plainly that it may be several people")

    # A single-work row cannot reach HIGH without an ORCID: there is not enough
    # evidence in one paper to assert an identity.
    band, _ = I.assess(orcid=None, raw_names=["X Y"], institution_years=[("I1", 2020)],
                       topic_fields=["CS"], works_in_corpus=1)
    bad += check(band != I.HIGH, f"single work with no ORCID reached {band}")

    # Mobility looks at any five-year window, not at the lifetime total: a long
    # career of normal moves must not read as a merge.
    band, _ = I.assess(
        orcid="0000-0001-0000-0000",
        raw_names=["Long Career"],
        institution_years=[("I1", 1990), ("I2", 2000), ("I3", 2010), ("I4", 2020)],
        topic_fields=["CS"] * 4,
        works_in_corpus=4,
    )
    bad += check(band == I.HIGH, f"a 30-year career of normal moves scored {band}")

    bad += check(I.hindex([]) == 0, "empty h-index")
    bad += check(I.hindex([10, 8, 5, 4, 3]) == 4, "h-index wrong")
    bad += check(I.hindex([1, 1, 1]) == 1, "h-index wrong on flat counts")

    print("test_identity:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
