#!/usr/bin/env python3
"""Semantic Scholar client with the repository's raw-first retention contract.

Semantic Scholar is an optional source of bibliographic metadata, not a
publisher scraper. A response is retained verbatim under its canonical hash
before a caller receives it, preserving the URL and time at which that
observation was made in the shared manifest.

The Graph API paper endpoint, queried with ``fields=externalIds,
references.externalIds``, carries both ends of each citation edge in one
envelope: the citing paper's own DOI alongside every reference's DOI. That is
the shape this adapter stores, mirroring a Crossref work envelope, so
``derive.py`` can resolve a citing/cited pair without a second lookup.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://api.semanticscholar.org/graph/v1/paper"

# Semantic Scholar's unauthenticated tier is documented at roughly one request
# per second. The request budget is an explicit operator limit, not a claim
# about Semantic Scholar's own quota.
REQUEST_COST = 1
DAILY_REQUESTS = 5_000
MAX_REQUESTS_PER_SECOND = 1.0
MAX_ATTEMPTS = 5

RAW_DIR = Path(__file__).parent / "harvest" / "raw"
MANIFEST = Path(__file__).parent / "harvest" / "manifest.jsonl"


class BudgetExhausted(RuntimeError):
    """Raised before a request would exceed the operator's daily budget."""


@dataclass(frozen=True)
class Fetched:
    """A stored Semantic Scholar paper response and the provenance to cite it."""

    url: str
    sha256: str
    path: Path
    fetched_at: str
    payload: dict

    def provenance(self) -> dict:
        return {"url": self.url, "sha256": self.sha256, "fetched_at": self.fetched_at}


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def normalize_doi(value: str) -> str:
    """Return a DOI from a bare DOI, ``doi:`` identifier, or resolver URL."""
    doi = urllib.parse.unquote(value.strip())
    parsed = urllib.parse.urlsplit(doi)
    if parsed.scheme and parsed.netloc.lower() in {"doi.org", "dx.doi.org"}:
        doi = parsed.path.lstrip("/")
    elif doi.lower().startswith("doi:"):
        doi = doi[4:].lstrip()
    if not doi.startswith("10.") or "/" not in doi:
        raise ValueError(f"not a DOI: {value!r}")
    return doi


class Client:
    """A polite, budgeted Semantic Scholar reader with injectable fixture transport."""

    def __init__(
        self,
        raw_dir: Path = RAW_DIR,
        budget: int = DAILY_REQUESTS,
        opener=None,
        sleeper=time.sleep,
        clock=time.monotonic,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.budget = budget
        self.spent = 0
        self._opener = opener or self._http
        self._sleeper = sleeper
        self._clock = clock
        self._last_request: float | None = None

    def _charge(self, cost: int) -> None:
        if self.spent + cost > self.budget:
            raise BudgetExhausted(
                f"{self.spent} of {self.budget} requests spent; "
                f"the next call costs {cost}"
            )
        self.spent += cost

    @property
    def remaining(self) -> int:
        return self.budget - self.spent

    def _http(self, url: str) -> dict:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "whocitedit/0.1 (+https://whocitedit.com)",
                     "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())

    def _throttle(self) -> None:
        now = self._clock()
        if self._last_request is not None:
            wait = 1.0 / MAX_REQUESTS_PER_SECOND - (now - self._last_request)
            if wait > 0:
                self._sleeper(wait)
        self._last_request = self._clock()

    def _fetch(self, url: str) -> dict:
        delay = 2.0
        for attempt in range(MAX_ATTEMPTS):
            try:
                payload = self._opener(url)
                if not isinstance(payload, dict):
                    raise ValueError("Semantic Scholar response was not a JSON object")
                return payload
            except urllib.error.HTTPError as exc:
                if exc.code != 429 and exc.code < 500:
                    raise
                if attempt == MAX_ATTEMPTS - 1:
                    raise
            except urllib.error.URLError:
                if attempt == MAX_ATTEMPTS - 1:
                    raise
            self._sleeper(delay)
            delay *= 2
        raise RuntimeError("unreachable")

    def _store(self, url: str, payload: dict) -> Fetched:
        body = _canonical(payload)
        sha = hashlib.sha256(body).hexdigest()
        path = self.raw_dir / sha[:2] / f"{sha}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(body)
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            rel = str(path.relative_to(Path(__file__).parent))
        except ValueError:
            rel = str(path)
        record = {"url": url, "sha256": sha, "fetched_at": fetched_at, "path": rel}
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        with MANIFEST.open("a") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        return Fetched(url, sha, path, fetched_at, payload)

    def _url(self, doi: str) -> str:
        # The DOI is a single path parameter: encode its slash too, so
        # punctuation in a DOI cannot become URL structure.
        doi_part = urllib.parse.quote(f"DOI:{normalize_doi(doi)}", safe="")
        return f"{BASE}/{doi_part}?fields=externalIds,references.externalIds"

    def references(self, doi: str) -> Fetched:
        """Fetch and store the paper envelope naming ``doi`` and its references."""
        self._charge(REQUEST_COST)
        url = self._url(doi)
        self._throttle()
        return self._store(url, self._fetch(url))


def reference_dois(payload: dict) -> list[str]:
    """Return the normalized, deduplicated, order-stable cited DOIs a paper asserts.

    Entries with no ``externalIds.DOI`` key, or a value ``normalize_doi()``
    rejects, are skipped. Mirrors ``crossref.reference_dois``.
    """
    dois: list[str] = []
    seen: set[str] = set()
    for entry in payload.get("references", []):
        raw = (entry.get("externalIds") or {}).get("DOI")
        if not raw:
            continue
        try:
            doi = normalize_doi(raw)
        except ValueError:
            continue
        if doi not in seen:
            seen.add(doi)
            dois.append(doi)
    return dois
