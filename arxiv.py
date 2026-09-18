#!/usr/bin/env python3
"""arXiv client with the repository's raw-first retention contract.

arXiv is an optional source of bibliographic metadata and citation
references, not a publisher scraper. A response is retained verbatim under
its canonical hash before a caller receives it, preserving the URL and time
at which that observation was made in the shared manifest.

arXiv's API answers Atom XML, not JSON. This adapter owns that conversion:
``parse_feed`` turns the Atom body into the plain dict this repository's
other adapters store directly, so ``derive.py``'s JSON-only raw reader needs
no special case for this source.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://export.arxiv.org/api/query"

ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"

# arXiv's API terms ask for at most one request every three seconds. The
# request budget is an explicit operator limit, not a claim about arXiv's own
# quota.
REQUEST_COST = 1
DAILY_REQUESTS = 5_000
MAX_REQUESTS_PER_SECOND = 1 / 3.0
MAX_ATTEMPTS = 5

RAW_DIR = Path(__file__).parent / "harvest" / "raw"
MANIFEST = Path(__file__).parent / "harvest" / "manifest.jsonl"


class BudgetExhausted(RuntimeError):
    """Raised before a request would exceed the operator's daily budget."""


@dataclass(frozen=True)
class Fetched:
    """A stored arXiv response and the provenance needed to cite it."""

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


def normalize_arxiv_id(value: str) -> str:
    """Return a bare arXiv id from a prefixed, versioned, or URL form.

    Accepts a bare id (``2401.00001``), an ``arXiv:`` prefixed id, an
    ``/abs/`` or ``/pdf/`` URL, and strips a trailing version suffix
    (``v2``).
    """
    id_ = value.strip()
    parsed = urllib.parse.urlsplit(id_)
    if parsed.scheme and parsed.netloc.lower() in {"arxiv.org", "export.arxiv.org"}:
        parts = parsed.path.strip("/").split("/", 1)
        id_ = parts[1] if len(parts) > 1 and parts[0] in {"abs", "pdf"} else parsed.path.strip("/")
    if id_.lower().startswith("arxiv:"):
        id_ = id_[len("arxiv:"):]
    if id_.lower().endswith(".pdf"):
        id_ = id_[:-4]
    id_ = re.sub(r"v\d+$", "", id_)
    if not id_:
        raise ValueError(f"not an arXiv id: {value!r}")
    return id_


def parse_feed(xml_text: str) -> dict:
    """Parse an arXiv Atom response into this repository's stored payload shape."""
    root = ET.fromstring(xml_text)
    entries = []
    for entry_el in root.findall(f"{{{ATOM_NS}}}entry"):
        id_text = (entry_el.findtext(f"{{{ATOM_NS}}}id") or "").strip()
        title_text = (entry_el.findtext(f"{{{ATOM_NS}}}title") or "").strip()
        doi_text = entry_el.findtext(f"{{{ARXIV_NS}}}doi")
        doi = doi_text.strip() if doi_text and doi_text.strip() else None
        references = []
        for ref_el in entry_el.findall(f"{{{ARXIV_NS}}}reference"):
            ref_doi = ref_el.get(f"{{{ARXIV_NS}}}doi")
            if ref_doi:
                references.append({"doi": ref_doi})
        entries.append({
            "id": id_text,
            "arxiv_id": normalize_arxiv_id(id_text) if id_text else "",
            "doi": doi,
            "title": title_text,
            "references": references,
        })
    return {"feed": {"entry": entries}}


class Client:
    """A polite, budgeted arXiv reader with injectable fixture transport."""

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
                     "Accept": "application/atom+xml"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return parse_feed(resp.read().decode())

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
                    raise ValueError("arXiv response was not a parsed feed object")
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

    def _query_url(self, doi_or_id: str) -> str:
        value = doi_or_id.strip()
        if value.startswith("10.") and "/" in value:
            params = {"search_query": f'doi:"{normalize_doi(value)}"'}
        else:
            params = {"id_list": normalize_arxiv_id(value)}
        return f"{BASE}?{urllib.parse.urlencode(params)}"

    def query(self, doi_or_id: str) -> Fetched:
        """Fetch and store arXiv's parsed feed for a DOI or arXiv id."""
        self._charge(REQUEST_COST)
        url = self._query_url(doi_or_id)
        self._throttle()
        return self._store(url, self._fetch(url))


def reference_dois(payload: dict) -> list[str]:
    """Return the normalized, deduplicated, order-stable DOIs a feed asserts.

    Mirrors ``crossref.reference_dois``: entries with no ``doi`` key, or a
    value ``normalize_doi()`` rejects, are skipped.
    """
    dois: list[str] = []
    seen: set[str] = set()
    for entry in payload.get("feed", {}).get("entry", []):
        for ref in entry.get("references", []):
            raw = ref.get("doi")
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
