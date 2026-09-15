"""The reviewable shapes accepted by :mod:`harvest` for corpus fields.

The original corpus file describes one field at its top level.  A future corpus
can put the same definitions below ``fields`` and choose their stable keys
explicitly.  Callers always receive the latter shape, without rewriting a
field's definition.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any


def field_key(name: str) -> str:
    """Return the deterministic key for a legacy field named ``name``."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    key = re.sub(r"[^a-z0-9]+", "-", folded.casefold()).strip("-")
    if not key:
        raise ValueError("a corpus field name must contain a letter or number")
    return key


def normalize(corpus: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return ``field key -> unchanged field definition`` for either contract.

    ``{"fields": {"stable-key": {...}}}`` is already normalized.  The
    legacy top-level definition gets a deterministic key from its ``name``.
    """
    if "fields" in corpus:
        fields = corpus["fields"]
        if not isinstance(fields, Mapping):
            raise ValueError("corpus fields must be a mapping")
        normalized = dict(fields)
    else:
        name = corpus.get("name")
        if not isinstance(name, str):
            raise ValueError("a legacy corpus definition must have a string name")
        normalized = {field_key(name): dict(corpus)}

    for key, definition in normalized.items():
        if not isinstance(key, str) or not key:
            raise ValueError("corpus field keys must be non-empty strings")
        if not isinstance(definition, Mapping):
            raise ValueError(f"corpus field {key!r} must be a mapping")
        normalized[key] = dict(definition)
    return normalized
