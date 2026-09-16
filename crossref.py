#!/usr/bin/env python3
"""Crossref work client with the repository's raw-first retention contract.

Crossref is an optional source of bibliographic metadata, not a publisher
scraper.  A response is retained verbatim under its canonical hash before a
caller receives it, preserving the URL and time at which that observation was
made in the shared manifest.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://api.crossref.org/works"

# Crossref asks clients to identify themselves and to avoid crowding the public
# service. The request budget is an explicit operator limit, not a claim about
# Crossref's own quota.
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
    """A stored Crossref work response and the provenance needed to cite it."""

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
    """A polite, budgeted Crossref reader with injectable fixture transport."""

    def __init__(
        self,
        mailto: str | None = None,
        raw_dir: Path = RAW_DIR,
        budget: int = DAILY_REQUESTS,
        opener=None,
        sleeper=time.sleep,
        clock=time.monotonic,
    ) -> None:
        self.mailto = mailto or os.environ.get("WHOCITEDIT_MAILTO") or ""
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
        agent = "whocitedit/0.1 (+https://whocitedit.com)"
        if self.mailto:
            agent += f" mailto:{self.mailto}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": agent, "Accept": "application/json"},
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
                    raise ValueError("Crossref work response was not a JSON object")
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
        # Crossref's DOI is a single path parameter: encode its slash too, so
        # punctuation in a DOI cannot become URL structure.
        url = f"{BASE}/{urllib.parse.quote(normalize_doi(doi), safe='')}"
        if self.mailto:
            url += "?" + urllib.parse.urlencode({"mailto": self.mailto})
        return url

    def work(self, doi: str) -> Fetched:
        """Fetch and store Crossref's work metadata for ``doi``."""
        self._charge(REQUEST_COST)
        url = self._url(doi)
        self._throttle()
        return self._store(url, self._fetch(url))
