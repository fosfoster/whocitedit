#!/usr/bin/env python3
"""What this site is allowed to render, and the evidence for each decision.

THIS FILE IS THE EDITORIAL SPINE AND IS IN `policy.deny_paths`. A builder that
could widen these rules could make its own unpublishable work publishable, which
is the first thing a stuck builder reaches for. Changing what may be rendered is
a human decision with a licence citation behind it, not a ticket.

The rule that matters: OpenAlex ships abstracts as an inverted index rather than
plaintext for legal reasons, and publishers have had them removed in bulk --
Springer Nature in November 2022, Elsevier in November 2024. So an abstract that
is present in the payload is NOT evidence we may republish it. We render an
abstract only when the work carries an open-access location under a licence that
permits redistribution. Everything else gets metadata, a graph, and a link out.

The coverage gap this creates is deliberate and is shown to the reader rather
than hidden. A page that quietly omits the reason it has no abstract is worse
than one that says "this work has no open licence we can redistribute under".
"""
from __future__ import annotations

# Licences that permit redistribution of the abstract text. Deliberately a
# closed allow-list: an unrecognised licence is treated as "not allowed", which
# fails toward the reader getting a link instead of toward us republishing
# something we may not.
REDISTRIBUTABLE_LICENSES = frozenset(
    {
        "cc0",
        "cc-by",
        "cc-by-sa",
        "cc-by-nd",
        "public-domain",
    }
)

# Recognised but NOT redistributable here. Named explicitly so that a licence
# landing in this set is a decision someone made rather than a string nobody
# recognised. NC forbids commercial redistribution and this site carries ads
# nowhere today but is not warranted non-commercial forever.
NON_REDISTRIBUTABLE_LICENSES = frozenset(
    {
        "cc-by-nc",
        "cc-by-nc-sa",
        "cc-by-nc-nd",
        "other-oa",
        "publisher-specific-oa",
    }
)

ABSTRACT_WITHHELD = "no-open-licence"
ABSTRACT_ABSENT = "not-in-source"
ABSTRACT_RENDERED = "rendered"


def normalize_license(raw: str | None) -> str | None:
    if not raw:
        return None
    return raw.strip().lower().replace("_", "-")


def may_render_abstract(license_id: str | None) -> bool:
    return normalize_license(license_id) in REDISTRIBUTABLE_LICENSES


def abstract_decision(work: dict) -> tuple[str | None, str, str | None]:
    """Return `(abstract_or_None, reason, licence)` for one OpenAlex work.

    `reason` is rendered on the page. A reader who sees no abstract is told
    which of the two reasons applies, because "the source has none" and "we are
    not allowed to show you this one" are different facts about the world and
    conflating them is the dishonest option.
    """
    best = work.get("best_oa_location") or work.get("primary_location") or {}
    license_id = normalize_license(best.get("license"))
    text = inverted_to_text(work.get("abstract_inverted_index"))
    if not text:
        return None, ABSTRACT_ABSENT, license_id
    if not may_render_abstract(license_id):
        return None, ABSTRACT_WITHHELD, license_id
    return text, ABSTRACT_RENDERED, license_id


def inverted_to_text(inverted: dict | None) -> str | None:
    """Rebuild plaintext from OpenAlex's `abstract_inverted_index`.

    The index maps each token to the positions it occupies. Rebuilding is only
    ever done behind `abstract_decision`, never on its own, so there is no path
    that reconstructs an abstract we are not allowed to show.
    """
    if not inverted:
        return None
    positions: list[tuple[int, str]] = []
    for token, idxs in inverted.items():
        for i in idxs:
            positions.append((i, token))
    if not positions:
        return None
    positions.sort()
    return " ".join(token for _, token in positions).strip() or None
