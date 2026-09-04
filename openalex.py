#!/usr/bin/env python3
"""OpenAlex client that stores every response verbatim before anything reads it.

Two rules shape this file.

RAW FIRST. Nothing in this repo parses a live HTTP response. `Client.get`
writes the bytes to a content-addressed file under `harvest/raw/` and returns a
`Fetched` naming that file, and `derive.py` reads only from there. Every number
the site renders therefore traces back to a stored payload and the URL it came
from, which is the same rule fund-tape runs on. It also means the whole derive
step replays offline, so a schema change costs no API credits.

BUDGET IS EXPLICIT. OpenAlex meters a credit allowance rather than a request
count, and the costs are not uniform -- a list request costs ten times a
singleton one. A harvester that counted requests would silently overrun by 10x,
so `Client` counts credits and refuses rather than getting itself rate-limited
halfway through a corpus.

Authentication is a slot, not a requirement. The API needs no key today, but
the free tier is metered against a Premium plan and the openalex-users list has
advertised a key requirement more than once. `OPENALEX_API_KEY` is read if it
is set so that the day it becomes mandatory is a config change here, not a
rewrite.
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

BASE = "https://api.openalex.org"

# https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication
# Free tier: 100,000 credits/day, 100 requests/second regardless of cost.
CREDITS_SINGLETON = 1
CREDITS_LIST = 10
CREDITS_CONTENT = 100
DAILY_CREDITS = 100_000

# Well under the documented 100/s. The limit that actually binds a harvest is
# the daily credit allowance, not throughput, so there is nothing to buy by
# crowding the per-second ceiling and a 429 costs more than the wait.
MAX_REQUESTS_PER_SECOND = 5.0

RAW_DIR = Path(__file__).parent / "harvest" / "raw"
MANIFEST = Path(__file__).parent / "harvest" / "manifest.jsonl"

# 200 is the documented maximum and the only page size worth using: a list
# request costs 10 credits whether it returns 1 row or 200, so a smaller page
# buys nothing and costs the same.
PER_PAGE = 200


class BudgetExhausted(RuntimeError):
    """Raised instead of overrunning the daily credit allowance."""


@dataclass(frozen=True)
class Fetched:
    """A stored payload plus the provenance needed to cite it."""

    url: str
    sha256: str
    path: Path
    fetched_at: str
    payload: dict

    def provenance(self) -> dict:
        return {"url": self.url, "sha256": self.sha256, "fetched_at": self.fetched_at}


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


class Client:
    """A polite, budgeted, replay-capable OpenAlex reader.

    `opener` exists so the tests can exercise paging, budgeting and the raw
    store without a network. It takes a URL and returns decoded JSON.
    """

    def __init__(
        self,
        mailto: str | None = None,
        api_key: str | None = None,
        raw_dir: Path = RAW_DIR,
        budget: int = DAILY_CREDITS,
        opener=None,
        sleeper=time.sleep,
    ) -> None:
        self.mailto = mailto or os.environ.get("WHOCITEDIT_MAILTO") or ""
        self.api_key = api_key or os.environ.get("OPENALEX_API_KEY") or ""
        self.raw_dir = Path(raw_dir)
        self.budget = budget
        self.spent = 0
        self._opener = opener or self._http
        self._sleeper = sleeper
        self._last_request = 0.0

    # -- budget ----------------------------------------------------------

    def _charge(self, credits: int) -> None:
        if self.spent + credits > self.budget:
            raise BudgetExhausted(
                f"{self.spent} of {self.budget} credits spent; "
                f"the next call costs {credits}"
            )
        self.spent += credits

    @property
    def remaining(self) -> int:
        return self.budget - self.spent

    # -- transport -------------------------------------------------------

    def _http(self, url: str) -> dict:
        # The mailto goes in the User-Agent as well as the query string. Both
        # are documented routes into the polite pool, and the header survives a
        # redirect that drops the query.
        agent = "whocitedit/0.1 (+https://whocitedit.com)"
        if self.mailto:
            agent += f" mailto:{self.mailto}"
        headers = {"User-Agent": agent, "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        delay = 2.0
        for attempt in range(5):
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as exc:
                # 429 and 5xx are worth waiting out. A 4xx that is not 429 is a
                # bad request and retrying it just spends the budget again.
                if exc.code != 429 and exc.code < 500:
                    raise
                if attempt == 4:
                    raise
                self._sleeper(delay)
                delay *= 2
            except urllib.error.URLError:
                if attempt == 4:
                    raise
                self._sleeper(delay)
                delay *= 2
        raise RuntimeError("unreachable")

    def _throttle(self) -> None:
        gap = 1.0 / MAX_REQUESTS_PER_SECOND
        wait = gap - (time.monotonic() - self._last_request)
        if wait > 0:
            self._sleeper(wait)
        self._last_request = time.monotonic()

    # -- storage ---------------------------------------------------------

    def _store(self, url: str, payload: dict) -> Fetched:
        body = _canonical(payload)
        sha = hashlib.sha256(body).hexdigest()
        path = self.raw_dir / sha[:2] / f"{sha}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(body)
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        # Repo-relative when the store is inside the repo, absolute otherwise.
        # `relative_to` raises rather than falling back, and a raw_dir pointed
        # somewhere else -- which is exactly what the tests do -- crashed the
        # write after the payload had already been saved.
        try:
            rel = str(path.relative_to(Path(__file__).parent))
        except ValueError:
            rel = str(path)
        record = {"url": url, "sha256": sha, "fetched_at": fetched_at, "path": rel}
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        with MANIFEST.open("a") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        return Fetched(url, sha, path, fetched_at, payload)

    # -- requests --------------------------------------------------------

    def _url(self, path: str, params: dict | None = None) -> str:
        query = dict(params or {})
        if self.mailto:
            query["mailto"] = self.mailto
        return f"{BASE}/{path.lstrip('/')}?{urllib.parse.urlencode(query)}"

    def singleton(self, path: str, params: dict | None = None) -> Fetched:
        self._charge(CREDITS_SINGLETON)
        url = self._url(path, params)
        self._throttle()
        return self._store(url, self._opener(url))

    def page(self, path: str, params: dict | None = None) -> Fetched:
        self._charge(CREDITS_LIST)
        url = self._url(path, params)
        self._throttle()
        return self._store(url, self._opener(url))

    def paginate(self, path: str, params: dict | None = None, max_records: int | None = None):
        """Cursor-paginate a list endpoint, yielding one `Fetched` per page.

        Cursor paging rather than `page=`: OpenAlex caps offset paging at 10,000
        records, which is inside the range this corpus reaches, and the cap
        presents as an error at record 10,001 rather than as a short result.
        """
        query = dict(params or {})
        query.setdefault("per-page", PER_PAGE)
        cursor = "*"
        seen = 0
        while cursor:
            query["cursor"] = cursor
            fetched = self.page(path, query)
            yield fetched
            results = fetched.payload.get("results") or []
            seen += len(results)
            if max_records is not None and seen >= max_records:
                return
            if not results:
                return
            cursor = (fetched.payload.get("meta") or {}).get("next_cursor")


def short_id(openalex_id: str | None) -> str | None:
    """`https://openalex.org/W2741809807` -> `W2741809807`.

    OpenAlex returns full URLs as ids and accepts the short form everywhere.
    Storing the short form keeps ids usable as path segments and as filenames,
    which is what the static export needs them for.
    """
    if not openalex_id:
        return None
    return openalex_id.rstrip("/").rsplit("/", 1)[-1]
