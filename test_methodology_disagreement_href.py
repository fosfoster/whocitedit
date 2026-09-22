#!/usr/bin/env python3
"""The six methodology disagreement cells link to their SOURCE_DISAGREEMENT_COHORTS route."""
import re
import sys
from pathlib import Path

import render
import test_full_corpus_render


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def main() -> int:
    bad = 0

    render_source = Path(render.__file__).read_text()
    for (field, source), config in render.SOURCE_DISAGREEMENT_COHORTS.items():
        occurrences = render_source.count(config["path"])
        bad += check(
            occurrences == 1,
            f"{config['path']!r} appears {occurrences} times in render.py; "
            "expected a single definition in SOURCE_DISAGREEMENT_COHORTS with no "
            "second route map",
        )

    with test_full_corpus_render.rendered_site() as site:
        html = (site / "methodology" / "index.html").read_text()

        for (field, source), config in render.SOURCE_DISAGREEMENT_COHORTS.items():
            expected_href = f'../{config["path"]}'
            link = re.search(
                rf'<td>{re.escape(config["source_label"])}</td>'
                rf'<td>{re.escape(config["field_label"])}</td>'
                r'.*?<a href="([^"]+)">',
                html,
            )
            bad += check(
                link is not None,
                f"no disagreement cell found for {config['source_label']} / {config['field_label']}",
            )
            if link is not None:
                bad += check(
                    link.group(1) == expected_href,
                    f"{config['source_label']} / {config['field_label']} cell href "
                    f"{link.group(1)!r} does not match SOURCE_DISAGREEMENT_COHORTS "
                    f"path {expected_href!r}",
                )

    if bad:
        print(f"FAILED: {bad} check(s)")
        return 1
    print("OK: methodology disagreement cells derive their hrefs from SOURCE_DISAGREEMENT_COHORTS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
