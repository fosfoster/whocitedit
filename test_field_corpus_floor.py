#!/usr/bin/env python3
"""Keep every declared corpus field above its recorded exported-work floor."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import corpus_contract


ROOT = Path(__file__).parent
DATA = ROOT / "web" / "data"

# These are the minimum retained counts from the committed corpus export.  A
# field must be added here in the same change that declares it in corpus.json.
FIELD_FLOORS = {
    "artificial-intelligence": 3000,
}


def load_json(path: Path):
    return json.loads(path.read_text())


def declared_fields() -> dict[str, dict]:
    """Resolve the source declaration into stable field keys."""
    return corpus_contract.normalize(load_json(ROOT / "corpus.json"))


def resolved_field_counts(fields: dict[str, dict]) -> dict[str, int]:
    """Resolve field membership counts from either supported export shape."""
    works = load_json(DATA / "works-index.json")
    exported_fields_path = DATA / "fields-index.json"
    membership_presence = ["fields" in work for work in works]

    if not exported_fields_path.exists() and not any(membership_presence):
        if len(fields) != 1:
            raise ValueError("legacy field export cannot resolve more than one declared field")
        return {next(iter(fields)): len(works)}

    if not exported_fields_path.exists() or not all(membership_presence):
        raise ValueError("incomplete field export: need fields-index.json and work fields arrays")

    exported_fields = load_json(exported_fields_path)
    if not isinstance(exported_fields, list):
        raise ValueError("fields-index.json must contain a list")
    exported_keys = [field.get("key") for field in exported_fields if isinstance(field, dict)]
    if len(exported_keys) != len(exported_fields) or len(set(exported_keys)) != len(exported_keys):
        raise ValueError("fields-index.json must name each field exactly once")
    if set(exported_keys) != set(fields):
        raise ValueError(
            "exported fields do not match declared fields: "
            f"declared {sorted(fields)}, exported {sorted(exported_keys)}"
        )

    counts = Counter()
    for work in works:
        memberships = work["fields"]
        if not isinstance(memberships, list):
            raise ValueError(f"work {work.get('id', '<unknown>')} has non-list field membership")
        if len(set(memberships)) != len(memberships) or any(key not in fields for key in memberships):
            raise ValueError(f"work {work.get('id', '<unknown>')} has invalid field membership")
        counts.update(memberships)

    for field in exported_fields:
        key = field["key"]
        if field.get("works") != counts[key]:
            raise ValueError(
                f"fields-index.json says {key} has {field.get('works')!r} works, "
                f"but work memberships resolve to {counts[key]}"
            )
    return {key: counts[key] for key in fields}


def main() -> int:
    try:
        fields = declared_fields()
        counts = resolved_field_counts(fields)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"test_field_corpus_floor: FAILED: {error}")
        return 1

    for key in sorted(counts):
        print(f"{key}: {counts[key]} works")

    bad = 0
    declared_keys = set(fields)
    floor_keys = set(FIELD_FLOORS)
    for key in sorted(declared_keys - floor_keys):
        print(f"  FAIL: declared field {key!r} has no FIELD_FLOORS entry")
        bad = 1
    for key in sorted(floor_keys - declared_keys):
        print(f"  FAIL: FIELD_FLOORS names undeclared field {key!r}")
        bad = 1
    for key in sorted(declared_keys & floor_keys):
        floor = FIELD_FLOORS[key]
        if not isinstance(floor, int) or floor < 0:
            print(f"  FAIL: FIELD_FLOORS[{key!r}] must be a non-negative integer")
            bad = 1
        elif counts[key] < floor:
            print(f"  FAIL: {key!r} has {counts[key]} works, below its floor of {floor}")
            bad = 1

    print("test_field_corpus_floor:", "FAILED" if bad else "ok")
    return bad


if __name__ == "__main__":
    sys.exit(main())
