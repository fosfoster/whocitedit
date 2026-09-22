#!/usr/bin/env python3
"""Guard against a second route/href map for the disagreement cells creeping
back into render.py -- SOURCE_DISAGREEMENT_COHORTS must stay the only source
of truth for those six works/{field}-disagreement/{source}/ paths."""
import ast
import re
import sys
from pathlib import Path

RENDER_PY = Path(__file__).parent / "render.py"

# The exact route shape the six disagreement cells resolve to, e.g.
# "works/title-disagreement/crossref/".
DISAGREEMENT_ROUTE_RE = re.compile(
    r"works/(?:title|venue|date)-disagreement/(?:crossref|europepmc)/"
)


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def disagreement_route_strings(node: ast.AST):
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            if DISAGREEMENT_ROUTE_RE.fullmatch(child.value):
                yield child.value


def dict_literals_mapping_disagreement_routes(tree: ast.Module):
    """Every module-level dict literal whose value carries two or more of the
    six disagreement-cell routes -- i.e. an actual field/source route map,
    not an incidental single mention (like the doi-year integrity cohort)."""
    mapping_literals = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            routes = set(disagreement_route_strings(node.value))
            if len(routes) >= 2:
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                mapping_literals.append((names, routes))
    return mapping_literals


def main() -> int:
    tree = ast.parse(RENDER_PY.read_text())
    mapping_literals = dict_literals_mapping_disagreement_routes(tree)

    bad = check(
        len(mapping_literals) == 1,
        "expected exactly one dict literal mapping routes/hrefs for the "
        f"disagreement cells, found {len(mapping_literals)}: {mapping_literals}",
    )
    bad += check(
        mapping_literals and mapping_literals[0][0] == ["SOURCE_DISAGREEMENT_COHORTS"],
        "SOURCE_DISAGREEMENT_COHORTS should be the sole map of disagreement-cell routes",
    )

    print("test_no_duplicate_route_map:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
