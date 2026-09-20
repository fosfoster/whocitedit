#!/usr/bin/env python3
"""Coverage for work_bibtex's @-entry type derived from bibtex_type()."""
import sys

import render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def base(work_id: str, work_type) -> dict:
    return {"id": work_id, "title": "Some Title", "type": work_type}


def main() -> int:
    bad = 0

    bad += check(render.work_bibtex(base("W1", "book")).startswith("@book{W1,"),
                 "a 'book' work did not render as @book")
    bad += check(render.work_bibtex(base("W2", "dissertation")).startswith("@phdthesis{W2,"),
                 "a 'dissertation' work did not render as @phdthesis")
    bad += check(render.work_bibtex(base("W3", "conference-paper")).startswith("@inproceedings{W3,"),
                 "a 'conference-paper' work did not render as @inproceedings")
    bad += check(render.work_bibtex(base("W4", "some-unknown-type")).startswith("@misc{W4,"),
                 "a work with an unrecognized type did not fall back to @misc")
    bad += check(render.work_bibtex({"id": "W5", "title": "Some Title"}).startswith("@misc{W5,"),
                 "a work with no type did not fall back to @misc")

    print("test_work_bibtex_types:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
