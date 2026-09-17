#!/usr/bin/env python3
"""How complete a work record is, and where it contradicts itself.

The sibling of `identity.py`, and the same argument. `identity.py` refuses to
pretend an author record is a person when the evidence is thin; this refuses to
pretend a work record is sound when the record disagrees with itself. In both
cases NOTHING IS DELETED OR CORRECTED -- the page says what is wrong with the
row it is showing, and the row stays.

The signals are the ones actually found in the first harvest, not invented ones:

  W4385245566  79,071 citations, ZERO authors, ZERO references, 2023
  W2896457183  46,036 citations, ZERO authors, DOI says 2022, record says 2018

Both are Schloss Dagstuhl LIPIcs records whose titles belong to other papers.
179 of 3,000 works carry no author at all.

DELIBERATELY NOT A SIGNAL: "this citation count is an implausible outlier". This
corpus is SELECTED by citation count, so every work in it is an outlier against
the population and a threshold fitted here would be fitted to the selection
rather than to the data. Saying a number is wrong requires evidence we do not
have on this tier, and the charter's rule is that surfacing a gap beats
implying a precision the source does not carry.
"""
from __future__ import annotations

import json
import re

COMPLETE = "complete"
PARTIAL = "partial"
SUSPECT = "suspect"

# The three-way verdict a title/date/venue signal can carry once Europe PMC's
# assertion is folded in alongside Crossref's. `agree`/`unavailable` collapse
# the same way the old two-way status did; the two disagreement cases only
# exist because a source can now disagree alone, and the reader needs to know
# which one, or a Europe-PMC-only contradiction reads identically to a
# three-way agreement.
AGREE = "agree"
CROSSREF_DISAGREES = "crossref_disagrees"
EUROPEPMC_DISAGREES = "europepmc_disagrees"
BOTH_DISAGREE = "both_disagree"
UNAVAILABLE = "unavailable"

# A DOI suffix very often embeds the year of the proceedings it belongs to.
# Where it does and the year disagrees with the record's own publication year,
# one of the two is wrong about which paper this is.
_DOI_YEAR = re.compile(r"(?:^|[./_-])((?:19|20)\d{2})(?:[./_-]|$)")

# A year apart is ordinary: online-first in December, issue in January.
DOI_YEAR_TOLERANCE = 1

# Below this, a work with no references recorded is unremarkable -- plenty of
# lightly cited records are simply thin. A heavily cited paper with no
# references at all is an incomplete record, not a paper that cited nothing.
NO_REFERENCES_CITATION_FLOOR = 1000

NOTE_TEMPLATES = {
    "authors": {
        "weakens": "The source lists no authors for this work at all, so there is nobody to attribute it to and it appears on no author page.",
        "supports": "{value} author record(s) attached.",
    },
    "references": {
        "weakens": "No references are recorded despite {value} citations. A paper this heavily cited did not cite nothing, so the record is incomplete.",
        "supports": "{value} reference(s) recorded.",
    },
    "doi_year": {
        "weakens": "The DOI names {doi_year} but the record dates this to {value}. One of the two is about a different paper.",
        "supports": "The DOI's year agrees with the publication year.",
        "neutral": "The DOI carries no year to check against.",
    },
    "title": {
        "weakens": "The source record carries no title.",
        "supports": "A title is present.",
    },
    "venue_source": {
        "weakens": "The sources disagree about this work's venue. Each is shown as a parallel observation; none is corrected here.",
        "supports": "The sources agree about this work's venue.",
        "neutral": "No comparable source assertion is available for this work's venue.",
    },
    "title_source": {
        "weakens": "The sources disagree about this work's title. Each is shown as a parallel observation; none is corrected here.",
        "supports": "The sources agree about this work's title.",
        "neutral": "No comparable source assertion is available for this work's title.",
    },
    "date_source": {
        "weakens": "The sources disagree about this work's publication date. Each is shown as a parallel observation; none is corrected here.",
        "supports": "The sources agree about this work's publication date.",
        "neutral": "No comparable source assertion is available for this work's publication date.",
    },
    "work_type_source": {
        "weakens": "OpenAlex and Crossref disagree about this work's type. Both are shown as parallel observations; neither is corrected here.",
        "supports": "Crossref's work-type assertion agrees with OpenAlex's.",
        "neutral": "No comparable Crossref work-type assertion is available.",
    },
}

BAND_SENTENCES = {
    COMPLETE: "Nothing in this record contradicts itself and no field we check is missing.",
    PARTIAL: "One field of this record is missing or disagrees with another. What is shown below is what the source publishes.",
    SUSPECT: "Several fields of this record are missing or contradict each other. Treat its figures with suspicion — it is shown unaltered because correcting a source's record silently is worse than showing you the problem.",
}


def doi_year(doi: str | None) -> int | None:
    if not doi:
        return None
    suffix = doi.rsplit("/", 1)[-1] if "10." in doi else doi
    years = [int(m) for m in _DOI_YEAR.findall(suffix)]
    return years[-1] if years else None


def source_verdict(crossref_status: str | None, europepmc_status: str | None) -> str:
    """Fold a Crossref-vs-OpenAlex status and a Europe-PMC-vs-OpenAlex status
    into one three-way verdict. `agree`/`unavailable`/`incomparable`/`None`
    are all "nothing contradicts OpenAlex here" on their own account; the only
    thing that matters is which source, if either, actively disagrees.
    """
    crossref_disagrees = crossref_status == "disagree"
    europepmc_disagrees = europepmc_status == "disagree"
    if crossref_disagrees and europepmc_disagrees:
        return BOTH_DISAGREE
    if crossref_disagrees:
        return CROSSREF_DISAGREES
    if europepmc_disagrees:
        return EUROPEPMC_DISAGREES
    if crossref_status == "agree" or europepmc_status == "agree":
        return AGREE
    return UNAVAILABLE


def assess(
    *,
    title: str | None,
    doi: str | None,
    year: int | None,
    n_authors: int,
    referenced_count: int,
    cited_by_count: int,
    venue_status: str | None = None,
    venue_europepmc_status: str | None = None,
    title_status: str | None = None,
    title_europepmc_status: str | None = None,
    date_status: str | None = None,
    date_europepmc_status: str | None = None,
    work_type_status: str | None = None,
) -> tuple[str, list[dict]]:
    evidence: list[dict] = []

    evidence.append(
        {
            "signal": "authors",
            "value": n_authors,
            "direction": "weakens" if n_authors == 0 else "supports",
        }
    )

    thin = referenced_count == 0 and cited_by_count >= NO_REFERENCES_CITATION_FLOOR
    evidence.append(
        {
            "signal": "references",
            "value": cited_by_count if thin else referenced_count,
            "direction": "weakens" if thin else "supports",
        }
    )

    dy = doi_year(doi)
    if dy is None or year is None:
        evidence.append({"signal": "doi_year", "value": year, "direction": "neutral"})
    else:
        off = abs(dy - year) > DOI_YEAR_TOLERANCE
        evidence.append(
            {
                "signal": "doi_year",
                "value": year,
                "doi_year": dy,
                "direction": "weakens" if off else "supports",
            }
        )

    missing_title = not title or title.startswith("[No title in the source record")
    evidence.append(
        {
            "signal": "title",
            "value": None,
            "direction": "weakens" if missing_title else "supports",
        }
    )

    # Only an explicit cross-source disagreement counts against the record.
    # `unavailable` (no comparable assertion) and `incomparable` (an unmapped
    # Crossref type) get the same neutral treatment `doi_year` gives a missing
    # year, so a corpus with no Crossref/Europe PMC harvest yet scores exactly
    # as it did before these signals existed. Europe PMC asserts no work type,
    # so work_type_source stays a two-way Crossref-vs-OpenAlex signal.
    for signal, crossref, europepmc in (
        ("venue_source", venue_status, venue_europepmc_status),
        ("title_source", title_status, title_europepmc_status),
        ("date_source", date_status, date_europepmc_status),
    ):
        verdict = source_verdict(crossref, europepmc)
        direction = "neutral" if verdict == UNAVAILABLE else "supports" if verdict == AGREE else "weakens"
        evidence.append({"signal": signal, "value": crossref, "verdict": verdict, "direction": direction})

    work_type_direction = (
        "supports" if work_type_status == "agree" else "weakens" if work_type_status == "disagree" else "neutral"
    )
    evidence.append({"signal": "work_type_source", "value": work_type_status, "direction": work_type_direction})

    weakened = sum(1 for e in evidence if e["direction"] == "weakens")
    band = COMPLETE if weakened == 0 else PARTIAL if weakened == 1 else SUSPECT
    return band, evidence


def band_sentence(band: str) -> str:
    return BAND_SENTENCES[band]


def encode_evidence(evidence: list[dict]) -> str:
    return json.dumps(evidence, sort_keys=True)


def decode_evidence(blob: str | None) -> list[dict]:
    return json.loads(blob) if blob else []
