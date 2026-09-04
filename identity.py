#!/usr/bin/env python3
"""How confident we are that one author row is one human being.

THIS IS THE HONESTY LAYER AND IT IS THE POINT OF THE SITE. OpenAlex author ids
are produced by an algorithm, not asserted by people. That algorithm splits one
researcher across several ids and merges several researchers into one, and every
tool built on top of it renders the result as though it were a fact. Doing the
same thing is the easy option and it is the one thing this site must not do.

So: no row is ever merged, dropped or silently corrected here. Instead every
author page states a confidence band and shows the signals behind it, and a
reader who disagrees can see exactly which signal we weighted. `low` means "this
page may be describing more than one person" and says so in those words.

The signals are deliberately cheap and legible. An embedding-similarity score
would probably rank better and would be impossible to explain on a page, which
makes it the wrong trade for this product.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter

HIGH = "high"
MEDIUM = "medium"
LOW = "low"

# THE PROSE LIVES HERE ONCE AND IS SHIPPED AS DATA. An earlier cut wrote the
# explanatory sentence into every author's evidence list, which was the same
# paragraph repeated 6,906 times -- 8 MB of one string. Worse, the reader would
# then have had to keep its own copy in TypeScript to render anything the
# exporter did not, and two copies of a sentence drift. `export_json.py` writes
# these templates into `corpus.json`; the reader formats `{value}` into them.
NOTE_TEMPLATES = {
    "orcid": {
        "supports": "An ORCID is claimed by a person, not inferred, so it is the only identity assertion here that a human made.",
        "neutral": "No ORCID on this record, so its identity rests on inference alone.",
    },
    "name_variants": {
        "supports": "{n} distinct name form(s) across this row's works, counting a spelled-out given name and its initial as one form.",
        "weakens": "{n} distinct name form(s) across this row's works. Several unrelated spellings is the usual shape of two people sharing one record.",
    },
    "institution_mobility": {
        "supports": "At most {value} distinct institution(s) inside any five-year window, which is a normal career.",
        "weakens": "At most {value} distinct institution(s) inside any five-year window. That is more moves than a career usually contains and is the usual shape of a merge.",
    },
    "topic_coherence": {
        "supports": "{pct} of this row's works sit in its single largest field.",
        "weakens": "Only {pct} of this row's works sit in its single largest field, so this record spreads across subjects a single researcher rarely spans.",
        "neutral": "No field information on this row's works.",
    },
    "works_in_corpus": {
        "neutral": "Confidence is judged on the {value} work(s) this corpus holds, not on the author's whole output. A single-work row carries little evidence either way.",
    },
}

BAND_SENTENCES = {
    HIGH: "This record carries a person-claimed ORCID and no signal that it mixes two people.",
    MEDIUM: "This record is probably one person, but at least one signal is weak. Check the evidence below before relying on the totals.",
    LOW: "This record may describe more than one person. It is shown as the source publishes it and has not been split or merged here.",
}

# An author who was at more than this many distinct institutions inside a single
# five-year window is more likely to be a merge than a very mobile researcher.
MOBILITY_CEILING = 5

# Below this share of works in the author's own top field, the row looks like
# two people with the same name rather than one person with range.
COHERENCE_FLOOR = 0.45


def normalize_name(raw: str | None) -> str:
    if not raw:
        return ""
    s = raw.lower()
    s = re.sub(r"[.’']", "", s)
    s = re.sub(r"[^a-zÀ-ɏ ]+", " ", s)
    return " ".join(s.split())


def initials_form(name: str) -> str:
    """`geoffrey e hinton` -> `g e hinton`.

    Two spellings that differ only by whether a given name is spelled out are
    the same person far more often than not, so they must not count as separate
    name variants -- otherwise every well-cited author scores as a merge risk.
    """
    parts = normalize_name(name).split()
    if len(parts) < 2:
        return normalize_name(name)
    return " ".join([p[0] for p in parts[:-1]] + [parts[-1]])


def assess(
    *,
    orcid: str | None,
    raw_names: list[str],
    institution_years: list[tuple[str, int | None]],
    topic_fields: list[str],
    works_in_corpus: int,
) -> tuple[str, list[dict]]:
    """Return `(band, evidence)`. Evidence is what the page renders."""
    evidence: list[dict] = []

    has_orcid = bool(orcid)
    evidence.append(
        {
            "signal": "orcid",
            "value": orcid or None,
            "direction": "supports" if has_orcid else "neutral",
        }
    )

    variants = {initials_form(n) for n in raw_names if n}
    variants.discard("")
    evidence.append(
        {
            "signal": "name_variants",
            "value": sorted(variants),
            "direction": "supports" if len(variants) <= 2 else "weakens",
        }
    )

    mobility = _peak_mobility(institution_years)
    evidence.append(
        {
            "signal": "institution_mobility",
            "value": mobility,
            "direction": "weakens" if mobility > MOBILITY_CEILING else "supports",
        }
    )

    coherence = _topic_coherence(topic_fields)
    evidence.append(
        {
            "signal": "topic_coherence",
            "value": round(coherence, 3) if coherence is not None else None,
            "direction": (
                "supports"
                if coherence is not None and coherence >= COHERENCE_FLOOR
                else "weakens" if coherence is not None else "neutral"
            ),
        }
    )

    evidence.append(
        {"signal": "works_in_corpus", "value": works_in_corpus, "direction": "neutral"}
    )

    weakened = sum(1 for e in evidence if e["direction"] == "weakens")
    if has_orcid and weakened == 0:
        band = HIGH
    elif has_orcid and weakened == 1:
        band = MEDIUM
    elif weakened == 0 and works_in_corpus >= 2:
        band = MEDIUM
    elif weakened >= 2:
        band = LOW
    else:
        band = MEDIUM if works_in_corpus >= 2 else LOW
    return band, evidence


def band_sentence(band: str) -> str:
    """The words the page uses. One definition, so the site cannot drift."""
    return BAND_SENTENCES[band]


def _peak_mobility(institution_years: list[tuple[str, int | None]]) -> int:
    dated = [(inst, yr) for inst, yr in institution_years if yr]
    if not dated:
        return len({inst for inst, _ in institution_years})
    peak = 0
    for _, start in dated:
        window = {inst for inst, yr in dated if start <= yr < start + 5}
        peak = max(peak, len(window))
    return peak


def _topic_coherence(topic_fields: list[str]) -> float | None:
    fields = [f for f in topic_fields if f]
    if not fields:
        return None
    return Counter(fields).most_common(1)[0][1] / len(fields)


def encode_evidence(evidence: list[dict]) -> str:
    return json.dumps(evidence, sort_keys=True)


def decode_evidence(blob: str | None) -> list[dict]:
    return json.loads(blob) if blob else []


def hindex(citation_counts: list[int]) -> int:
    """Reported on author pages only alongside the confidence band.

    An h-index computed over a merged row is a number about two people, which is
    exactly why it never appears without the band next to it.
    """
    counts = sorted(citation_counts, reverse=True)
    h = 0
    for i, c in enumerate(counts, start=1):
        if c >= i:
            h = i
        else:
            break
    return h


def log_scaled(n: int) -> float:
    return math.log1p(max(n, 0))
