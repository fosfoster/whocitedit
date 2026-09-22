#!/usr/bin/env python3
"""Direct coverage for the source-disagreement cohort href helper."""
import sys

import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def main() -> int:
    bad = 0

    for cohort, config in render.SOURCE_DISAGREEMENT_COHORTS.items():
        href = render.href_for_cohort(cohort)
        bad += check(href == "/" + config["path"],
                     f"{cohort} href does not match its configured path")
        bad += check(href.startswith("/"),
                     f"{cohort} href is not site-root-relative")
        bad += check(href.endswith("/"),
                     f"{cohort} href does not end with a trailing slash")

    print("test_href_helper:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
