#!/usr/bin/env python3
"""COCI outgoing-reference client with the same raw-first contract as OpenAlex.

COCI returns a JSON list for a DOI, rather than OpenAlex's paginated mapping.
The list is stored verbatim before a caller sees it, so a later reconciliation
of DOI citation edges can replay the source without another network request.
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

BASE = "https://opencitations.net/index/coci/api/v1"

# COCI does not charge credits, but its public API is still a shared resource.
# Keep an explicit operator budget so a DOI sweep cannot run without a bound.
REQUEST_COST = 1
DAILY_REQUESTS = 10_000
MAX_REQUESTS_PER_SECOND = 5.0
MAX_ATTEMPTS = 5

RAW_DIR = Path(__file__).parent / "harvest" / "raw"
MANIFEST = Path(__file__).parent / "harvest" / "manifest.jsonl"


class BudgetExhausted(RuntimeError):
    """Raised before a request would exceed the operator's daily budget."""


@dataclass(frozen=True)
class Fetched:
    """A stored COCI list plus the provenance needed to cite it."""

    url: str
    sha256: str
    path: Path
    fetched_at: str
    payload: list[dict]

    def provenance(self) -> dict:
        return {"url": self.url, "sha256": self.sha256, "fetched_at": self.fetched_at}


def _canonical(payload: list[dict]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def normalize_doi(value: str) -> str:
    """Return a DOI from either a bare DOI or a DOI resolver URL."""
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
    """A polite, budgeted COCI reader.

    Tests pass an ``opener`` that returns decoded fixture JSON. Production uses
    the same shape through ``_http``; neither parsing nor storage knows which
    transport supplied the response.
    """

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

    def _http(self, url: str) -> list[dict]:
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

    def _fetch(self, url: str) -> list[dict]:
        delay = 2.0
        for attempt in range(MAX_ATTEMPTS):
            try:
                payload = self._opener(url)
                if not isinstance(payload, list):
                    raise ValueError("COCI references response was not a JSON list")
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

    def _store(self, url: str, payload: list[dict]) -> Fetched:
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
        # A slash is part of every DOI's readable form; encode every other
        # path-significant character so the identifier remains one endpoint.
        return f"{BASE}/references/{urllib.parse.quote(normalize_doi(doi), safe='/')}"

    def references(self, doi: str) -> Fetched:
        """Fetch and store the outgoing COCI references for ``doi``."""
        self._charge(REQUEST_COST)
        url = self._url(doi)
        self._throttle()
        return self._store(url, self._fetch(url))
