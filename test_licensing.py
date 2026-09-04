#!/usr/bin/env python3
"""The abstract rule is the one that carries legal weight, so it is tested by
enumeration rather than by example: no licence outside the allow-list may ever
produce rendered text, including licences nobody has seen yet."""
import sys

import licensing as L


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def main() -> int:
    bad = 0

    # The claim in licensing.py's docstring is "we render an abstract only when
    # the work carries an open-access location under a licence that permits
    # redistribution". This is the test that would falsify it.
    index = {"Hello": [0], "world": [1]}
    universe = (
        list(L.REDISTRIBUTABLE_LICENSES)
        + list(L.NON_REDISTRIBUTABLE_LICENSES)
        + ["CC-BY", "cc_by", None, "", "elsevier-specific", "made-up-licence", "cc-by-nc-nd"]
    )
    for lic in universe:
        work = {"best_oa_location": {"license": lic}, "abstract_inverted_index": index}
        text, reason, _ = L.abstract_decision(work)
        allowed = L.normalize_license(lic) in L.REDISTRIBUTABLE_LICENSES
        bad += check(
            bool(text) == allowed,
            f"licence {lic!r}: text={bool(text)} but allowed={allowed}",
        )
        bad += check(
            reason == (L.ABSTRACT_RENDERED if allowed else L.ABSTRACT_WITHHELD),
            f"licence {lic!r}: reason {reason}",
        )

    # An unknown licence must fail closed, not open.
    bad += check(not L.may_render_abstract("some-new-licence-2027"), "unknown licence rendered")

    # No index at all is a different fact from a withheld one, and the page
    # says which. Conflating them is the dishonest option.
    text, reason, _ = L.abstract_decision({"best_oa_location": {"license": "cc-by"}})
    bad += check(text is None and reason == L.ABSTRACT_ABSENT, "missing index misreported")

    # Reconstruction has to respect positions, not dict order.
    out = L.inverted_to_text({"world": [1], "Hello": [0], "again": [2]})
    bad += check(out == "Hello world again", f"inverted reconstruction wrong: {out!r}")
    bad += check(L.inverted_to_text(None) is None, "None index should be None")
    bad += check(L.inverted_to_text({}) is None, "empty index should be None")

    # `primary_location` is the fallback when there is no best_oa_location, and
    # it must obey the same rule rather than being a way around it.
    text, reason, _ = L.abstract_decision(
        {"primary_location": {"license": "cc-by-nc"}, "abstract_inverted_index": index}
    )
    bad += check(text is None, "primary_location bypassed the licence rule")

    print("test_licensing:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
