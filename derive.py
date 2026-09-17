#!/usr/bin/env python3
"""Turn stored raw payloads into the corpus database. No network.

Replayable by construction: this reads `harvest/raw/` and nothing else, so a
schema change or a scoring change costs zero API credits and produces a database
that still traces every row to the bytes it came from.

The one rule worth stating up front: A CITATION EDGE IS ONLY STORED WHEN BOTH
ENDS ARE IN THE CORPUS. OpenAlex hands us `referenced_works` for every work,
most of which point outside a 3,000-work set. Storing those would give the site
dangling nodes it can render nothing for, and would make `cited_by_count` inside
the graph disagree with the number shown beside it. Works keep their global
`cited_by_count` as published; the graph is explicitly the in-corpus subgraph and
the pages say so.
"""
from __future__ import annotations

import html
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import crossref
import graph
import identity
import quality
from corpus_contract import normalize
from db import DB_PATH, connect, set_meta
from licensing import abstract_decision
from openalex import short_id
from opencitations import normalize_doi

ROOT = Path(__file__).parent
RAW = ROOT / "harvest" / "raw"
MANIFEST = ROOT / "harvest" / "manifest.jsonl"
CORPUS = ROOT / "corpus.json"


def _manifest_index() -> dict[str, list[dict]]:
    """sha256 -> every manifest observation of that stored payload."""
    index: dict[str, list[dict]] = {}
    if not MANIFEST.exists():
        return index
    for line in MANIFEST.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        index.setdefault(rec["sha256"], []).append(rec)
    return index


def _payloads():
    manifest = _manifest_index()
    for path in sorted(RAW.rglob("*.json")):
        sha = path.stem
        observations = manifest.get(sha) or [{
            "url": "unknown",
            "fetched_at": "unknown",
            "path": str(path.relative_to(ROOT)),
            "sha256": sha,
        }]
        # The raw table still has one provenance record per payload.  Keep the
        # previous newest-observation behaviour for that record while carrying
        # every observation below for field membership.
        yield observations[-1], observations, json.loads(path.read_text())


def _is_work(obj: dict) -> bool:
    return "authorships" in obj or "referenced_works" in obj


def _is_author(obj: dict) -> bool:
    return "display_name" in obj and "works_count" in obj and "authorships" not in obj


def _is_crossref_work_envelope(payload: dict) -> bool:
    return payload.get("message-type") == "work" and isinstance(payload.get("message"), dict)


def _is_europepmc_search(payload: dict) -> bool:
    return "resultList" in payload


def _is_europepmc_references(payload: dict) -> bool:
    return "referenceList" in payload


def _is_europepmc_search_envelope(payload: dict) -> bool:
    """A Europe PMC search response: `resultList` is a dict holding a `result` list.

    Stricter than `_is_europepmc_search` above, whose membership check alone is
    enough for the citing-DOI index but would also accept a malformed payload.
    An OpenAlex `results` payload, a Crossref work envelope, and the Europe PMC
    *references* payload (`referenceList`, not `resultList`) all fail this.
    """
    result_list = payload.get("resultList")
    return isinstance(result_list, dict) and isinstance(result_list.get("result"), list)


def _load_fields(conn) -> dict[str, dict]:
    definitions = normalize(json.loads(CORPUS.read_text()))
    if not definitions:
        raise ValueError("corpus must define at least one field")
    conn.executemany(
        "INSERT INTO corpus_field(key, definition) VALUES(?, ?)",
        [
            (key, json.dumps(definition, sort_keys=True, separators=(",", ":")))
            for key, definition in sorted(definitions.items())
        ],
    )
    return definitions


def _field_keys(observations: list[dict], definitions: dict[str, dict], sha: str) -> list[str]:
    """Return all configured fields that selected a source-work payload."""
    keys: set[str] = set()
    unknown = []
    missing = False
    for rec in observations:
        if "field_key" not in rec:
            missing = True
            continue
        key = rec["field_key"]
        if not isinstance(key, str) or key not in definitions:
            unknown.append(key)
            continue
        keys.add(key)
    if unknown:
        raise ValueError(
            f"unknown field membership {unknown!r} for work payload {sha}"
        )
    if missing and len(definitions) > 1:
        raise ValueError(
            f"missing field membership for work payload {sha} in a multi-field corpus"
        )
    if not keys:
        if len(definitions) == 1:
            # Old manifests predate field_key.  Their sole corpus definition is
            # unambiguous, so preserve that corpus rather than discarding it.
            return [next(iter(definitions))]
        raise ValueError(f"missing field membership for work payload {sha}")
    return sorted(keys)


def load(conn) -> dict:
    stats = {"payloads": 0, "works": 0, "authors": 0, "authorships": 0}
    references: dict[str, list[str]] = {}
    coci_assertions: list[tuple[str, str]] = []
    crossref_envelopes: list[tuple[str, dict]] = []
    crossref_reference_assertions: list[tuple[str, str]] = []
    europepmc_search_dois: dict[tuple[str, str], str] = {}
    europepmc_reference_assertions: list[tuple[tuple[str, str], str]] = []
    europepmc_results: list[tuple[str, dict]] = []
    definitions = _load_fields(conn)

    for rec, observations, payload in _payloads():
        stats["payloads"] += 1
        conn.execute(
            "INSERT OR REPLACE INTO raw_payload(sha256, url, fetched_at, path) "
            "VALUES(?,?,?,?)",
            (rec["sha256"], rec["url"], rec["fetched_at"], rec["path"]),
        )
        # COCI stores outgoing references as a top-level list. Reconcile those
        # DOI pairs after every OpenAlex work is present, so either endpoint can
        # be resolved against the completed in-corpus DOI index.
        if not isinstance(payload, dict):
            if isinstance(payload, list):
                coci_assertions.extend(
                    (obj.get("citing"), obj.get("cited"))
                    for obj in payload
                    if isinstance(obj, dict)
                )
            continue
        # Crossref's stored envelope wraps a single work in "message", rather
        # than OpenAlex's "results" list. Collect it now but reconcile by DOI
        # only after every OpenAlex work is inserted below, so the match does
        # not depend on the (hash-ordered) order raw files are visited in.
        if _is_crossref_work_envelope(payload):
            message = payload["message"]
            crossref_envelopes.append((rec["sha256"], message))
            citing_doi = message.get("DOI")
            if citing_doi:
                crossref_reference_assertions.extend(
                    (citing_doi, cited_doi) for cited_doi in crossref.reference_dois(payload)
                )
            continue
        # Europe PMC's DOI search echoes the (source, id) pair its references
        # endpoint uses to name the citing article, but never a citing DOI
        # directly. Index every search result's (source, id) -> doi here, and
        # resolve the references payload's echoed key against it below, after
        # every search payload has been visited.
        if _is_europepmc_search(payload):
            for result in (payload.get("resultList") or {}).get("result") or []:
                if not isinstance(result, dict):
                    continue
                source, ext_id, doi = result.get("source"), result.get("id"), result.get("doi")
                if source and ext_id and doi:
                    europepmc_search_dois[(source, ext_id)] = doi
            # Collect the same results now but reconcile by DOI only after every
            # OpenAlex work is inserted below, exactly like the Crossref
            # envelopes above, so the match does not depend on raw-file order.
            if _is_europepmc_search_envelope(payload):
                europepmc_results.extend(
                    (rec["sha256"], result)
                    for result in payload["resultList"]["result"]
                    if isinstance(result, dict)
                )
            continue
        if _is_europepmc_references(payload):
            request = payload.get("request") or {}
            citing_key = (request.get("source"), request.get("id"))
            for ref in (payload.get("referenceList") or {}).get("reference") or []:
                if isinstance(ref, dict) and ref.get("doi"):
                    europepmc_reference_assertions.append((citing_key, ref["doi"]))
            continue
        for obj in payload.get("results") or []:
            if _is_work(obj):
                wid = _insert_work(conn, obj, rec["sha256"])
                conn.executemany(
                    "INSERT OR IGNORE INTO work_corpus_field(work_id, field_key) VALUES(?, ?)",
                    [(wid, field_key) for field_key in _field_keys(observations, definitions, rec["sha256"])],
                )
                references[wid] = [
                    short_id(r) for r in (obj.get("referenced_works") or [])
                ]
                stats["works"] += 1
            elif _is_author(obj):
                _insert_author(conn, obj, rec["sha256"])
                stats["authors"] += 1

    stats["authorships"] = conn.execute("SELECT COUNT(*) c FROM authorship").fetchone()["c"]
    stats["citations"] = _insert_citations(
        conn, references, coci_assertions,
        europepmc_search_dois, europepmc_reference_assertions,
        crossref_reference_assertions,
    )
    stats["crossref_assertions"] = _insert_crossref_assertions(conn, crossref_envelopes)
    stats["europepmc_assertions"] = _insert_europepmc_assertions(conn, europepmc_results)
    return stats


NO_TITLE_PREFIX = "[No title in the source record"


def _title(w: dict) -> str:
    """Never the bare word "Untitled".

    Seven works in the first harvest carry no title at all, and rendering them as
    a row that says "Untitled" tells a reader nothing and looks like our bug
    rather than the source's gap. Fall back to what the record does have, and
    say plainly that the title is missing upstream.
    """
    title = (w.get("title") or "").strip()
    if title:
        return title
    src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name")
    hint = src or (w.get("doi") or "").replace("https://doi.org/", "") or short_id(w["id"])
    return f"{NO_TITLE_PREFIX} — {hint}]"


def _insert_institution(conn, inst: dict, raw_sha: str | None) -> str | None:
    iid = short_id(inst.get("id"))
    if not iid:
        return None
    conn.execute(
        "INSERT INTO institution(id, display_name, ror, country_code, type, raw_sha) "
        "VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
        "display_name=excluded.display_name, ror=excluded.ror, "
        "country_code=excluded.country_code, type=excluded.type, raw_sha=excluded.raw_sha",
        (
            iid,
            inst.get("display_name") or iid,
            inst.get("ror"),
            inst.get("country_code"),
            inst.get("type"),
            raw_sha,
        ),
    )
    if raw_sha:
        conn.execute(
            "INSERT OR IGNORE INTO institution_payload(institution_id, raw_sha) VALUES(?,?)",
            (iid, raw_sha),
        )
    return iid


def _insert_topic(conn, topic: dict, raw_sha: str | None) -> str | None:
    tid = short_id(topic.get("id"))
    if not tid:
        return None
    conn.execute(
        "INSERT INTO topic(id, display_name, field, domain, raw_sha) VALUES(?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name, "
        "field=excluded.field, domain=excluded.domain, raw_sha=excluded.raw_sha",
        (
            tid,
            topic.get("display_name") or tid,
            (topic.get("field") or {}).get("display_name"),
            (topic.get("domain") or {}).get("display_name"),
            raw_sha,
        ),
    )
    if raw_sha:
        conn.execute(
            "INSERT OR IGNORE INTO topic_payload(topic_id, raw_sha) VALUES(?,?)",
            (tid, raw_sha),
        )
    return tid


def _insert_work(conn, w: dict, raw_sha: str) -> str:
    wid = short_id(w["id"])
    abstract, reason, license_id = abstract_decision(w)
    best = w.get("best_oa_location") or {}
    src = (w.get("primary_location") or {}).get("source") or {}
    conn.execute(
        """INSERT INTO work(
             id, doi, title, year, publication_date, type, source_id, source_name,
             is_oa, oa_status, oa_url, oa_license, abstract, abstract_reason,
             cited_by_count, referenced_count, is_seed, raw_sha)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)
           ON CONFLICT(id) DO UPDATE SET doi=excluded.doi, title=excluded.title,
             year=excluded.year, publication_date=excluded.publication_date,
             type=excluded.type, source_id=excluded.source_id,
             source_name=excluded.source_name, is_oa=excluded.is_oa,
             oa_status=excluded.oa_status, oa_url=excluded.oa_url,
             oa_license=excluded.oa_license, abstract=excluded.abstract,
             abstract_reason=excluded.abstract_reason,
             cited_by_count=excluded.cited_by_count,
             referenced_count=excluded.referenced_count,
             is_seed=excluded.is_seed, raw_sha=excluded.raw_sha""",
        (
            wid,
            w.get("doi"),
            _title(w),
            w.get("publication_year"),
            w.get("publication_date"),
            w.get("type"),
            short_id(src.get("id")),
            src.get("display_name"),
            1 if (w.get("open_access") or {}).get("is_oa") else 0,
            (w.get("open_access") or {}).get("oa_status"),
            best.get("landing_page_url") or (w.get("open_access") or {}).get("oa_url"),
            license_id,
            abstract,
            reason,
            w.get("cited_by_count") or 0,
            len(w.get("referenced_works") or []),
            raw_sha,
        ),
    )
    conn.execute(
        "INSERT OR IGNORE INTO work_payload(work_id, raw_sha) VALUES(?,?)",
        (wid, raw_sha),
    )

    for topic in (w.get("topics") or [])[:3]:
        tid = _insert_topic(conn, topic, raw_sha)
        if not tid:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO work_topic(work_id, topic_id, score) VALUES(?,?,?)",
            (wid, tid, topic.get("score")),
        )

    for ordinal, a in enumerate(w.get("authorships") or []):
        aid = short_id((a.get("author") or {}).get("id"))
        if not aid:
            continue
        # A stub row so the foreign key holds even when the author payload has
        # not been harvested yet. `_insert_author` fills it in later; a corpus
        # with a missing author fetch degrades to a name, not to a crash.
        conn.execute(
            "INSERT OR IGNORE INTO author(id, display_name) VALUES(?,?)",
            (aid, (a.get("author") or {}).get("display_name") or aid),
        )
        conn.execute(
            "INSERT OR REPLACE INTO authorship("
            "  work_id, author_id, ordinal, author_position, raw_name, is_corresponding)"
            " VALUES(?,?,?,?,?,?)",
            (
                wid,
                aid,
                ordinal,
                a.get("author_position"),
                a.get("raw_author_name"),
                1 if a.get("is_corresponding") else 0,
            ),
        )
        for inst in a.get("institutions") or []:
            iid = _insert_institution(conn, inst, raw_sha)
            if not iid:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO affiliation(author_id, institution_id, work_id, year)"
                " VALUES(?,?,?,?)",
                (aid, iid, wid, w.get("publication_year")),
            )
    return wid


def _insert_author(conn, a: dict, raw_sha: str) -> None:
    aid = short_id(a["id"])
    insts = a.get("last_known_institutions") or []
    for inst in insts:
        _insert_institution(conn, inst, raw_sha)
    conn.execute(
        "INSERT INTO author(id, display_name, orcid, works_count, cited_by_count, raw_sha)"
        " VALUES(?,?,?,?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name,"
        "   orcid=excluded.orcid, works_count=excluded.works_count,"
        "   cited_by_count=excluded.cited_by_count, raw_sha=excluded.raw_sha",
        (
            aid,
            a.get("display_name") or aid,
            (a.get("orcid") or "").rsplit("/", 1)[-1] or None,
            a.get("works_count") or 0,
            a.get("cited_by_count") or 0,
            raw_sha,
        ),
    )
    conn.execute(
        "INSERT OR IGNORE INTO author_payload(author_id, raw_sha) VALUES(?,?)",
        (aid, raw_sha),
    )


def _normalized_doi(value: str | None) -> str | None:
    """Canonical DOI key for matching COCI and OpenAlex identifiers."""
    if not isinstance(value, str):
        return None
    try:
        return normalize_doi(value).lower()
    except ValueError:
        return None


def _insert_citations(conn, references: dict[str, list[str]],
                      coci_assertions: list[tuple[str, str]],
                      europepmc_search_dois: dict[tuple[str, str], str],
                      europepmc_reference_assertions: list[tuple[tuple[str, str], str]],
                      crossref_reference_assertions: list[tuple[str, str]]) -> int:
    in_corpus = {r["id"] for r in conn.execute("SELECT id FROM work")}
    assertions: dict[tuple[str, str], set[str]] = {}

    for citing, cited_ids in references.items():
        for cited in cited_ids:
            if cited in in_corpus and cited != citing:
                assertions.setdefault((citing, cited), set()).add("openalex")

    doi_to_work = {}
    for row in conn.execute("SELECT id, doi FROM work ORDER BY id"):
        doi = _normalized_doi(row["doi"])
        if doi:
            doi_to_work.setdefault(doi, row["id"])
    for citing_doi, cited_doi in coci_assertions:
        citing = doi_to_work.get(_normalized_doi(citing_doi))
        cited = doi_to_work.get(_normalized_doi(cited_doi))
        if citing and cited and citing != cited:
            assertions.setdefault((citing, cited), set()).add("opencitations")

    # A Europe PMC references payload names its citing article by (source, id),
    # never by DOI. Resolve that key against the stored search payload's echo
    # of the same pair before it can be joined to the in-corpus DOI index; an
    # unresolved key is dropped silently, exactly as an unknown COCI DOI is.
    for citing_key, cited_doi in europepmc_reference_assertions:
        citing_doi = europepmc_search_dois.get(citing_key)
        citing = doi_to_work.get(_normalized_doi(citing_doi))
        cited = doi_to_work.get(_normalized_doi(cited_doi))
        if citing and cited and citing != cited:
            assertions.setdefault((citing, cited), set()).add("europepmc")

    # A Crossref work envelope's `reference` array names cited DOIs directly,
    # so no key resolution is needed here, unlike Europe PMC above. Resolve
    # both ends against the same in-corpus DOI index and drop an unresolved
    # DOI or self-pair silently, exactly as COCI and Europe PMC do.
    for citing_doi, cited_doi in crossref_reference_assertions:
        citing = doi_to_work.get(_normalized_doi(citing_doi))
        cited = doi_to_work.get(_normalized_doi(cited_doi))
        if citing and cited and citing != cited:
            assertions.setdefault((citing, cited), set()).add("crossref")

    rows = [
        (citing, cited, graph.encode_sources(list(sources)))
        for (citing, cited), sources in sorted(assertions.items())
    ]
    conn.executemany(
        "INSERT INTO citation(citing_id, cited_id, sources) VALUES(?,?,?) "
        "ON CONFLICT(citing_id, cited_id) DO UPDATE SET sources=excluded.sources",
        rows,
    )
    return conn.execute("SELECT COUNT(*) c FROM citation").fetchone()["c"]


def _first(values) -> str | None:
    return values[0] if isinstance(values, list) and values else None


def _crossref_title(message: dict) -> str | None:
    """Crossref's first title as plain text.

    Crossref titles carry inline JATS/HTML markup (`<i>`, `<sub>`) and entities.
    Strip those and nothing else: the stored value is what Crossref asserted,
    and `normalize_title` below is the only place comparison folding happens.
    """
    title = _first(message.get("title"))
    if not isinstance(title, str):
        return None
    text = html.unescape(re.sub(r"<[^>]*>", "", title))
    text = " ".join(text.split())
    return text or None


# Crossref's `issued` is its own earliest-known publication date. The rest are
# fallbacks in a fixed order so the stored assertion does not depend on which
# keys a given record happens to carry.
CROSSREF_DATE_KEYS = ("issued", "published", "published-online", "published-print")


def _crossref_date(message: dict) -> str | None:
    """A date at exactly the precision Crossref supplied, never padded."""
    for key in CROSSREF_DATE_KEYS:
        block = message.get(key)
        parts = _first(block.get("date-parts")) if isinstance(block, dict) else None
        if not isinstance(parts, list):
            continue
        fields = []
        for part in parts[:3]:
            if isinstance(part, bool) or not isinstance(part, int):
                break
            fields.append(part)
        if not fields:
            continue
        return "-".join([f"{fields[0]:04d}"] + [f"{p:02d}" for p in fields[1:]])
    return None


def _insert_crossref_assertions(conn, envelopes: list[tuple[str, dict]]) -> int:
    """Join stored Crossref work envelopes to the corpus by normalized DOI.

    Runs after every OpenAlex work is in place, so a Crossref payload whose
    DOI is not (yet, or ever) in the corpus is simply dropped rather than
    stored dangling. Only the columns named here are retained: a Crossref
    abstract, author list, reference list or citation count never reaches
    the database, so it can never reach a page either.
    """
    doi_to_work: dict[str, str] = {}
    for row in conn.execute("SELECT id, doi FROM work"):
        doi = _normalized_doi(row["doi"])
        if doi:
            doi_to_work.setdefault(doi, row["id"])

    count = 0
    for raw_sha, message in envelopes:
        wid = doi_to_work.get(_normalized_doi(message.get("DOI")))
        if not wid:
            continue
        conn.execute(
            "INSERT INTO crossref_work_assertion("
            "  work_id, raw_sha, venue, venue_short, work_type, title, published) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(work_id, raw_sha) DO UPDATE SET "
            "venue=excluded.venue, venue_short=excluded.venue_short, work_type=excluded.work_type, "
            "title=excluded.title, published=excluded.published",
            (
                wid,
                raw_sha,
                _first(message.get("container-title")),
                _first(message.get("short-container-title")),
                message.get("type"),
                _crossref_title(message),
                _crossref_date(message),
            ),
        )
        count += 1
    return count


def normalize_title(value: str) -> str:
    """Comparison-only folding: accents, case, punctuation and spacing.

    Never stored and never rendered. Two sources that differ by a trailing
    full stop or an italicised species name are not disagreeing about what
    the paper is called.
    """
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded.casefold()).split())


def title_comparison_status(openalex_title: str | None, crossref_title: str | None) -> str:
    # The OpenAlex placeholder for a missing title is ours, not the source's:
    # comparing it would report a disagreement OpenAlex never asserted.
    if not openalex_title or openalex_title.startswith(NO_TITLE_PREFIX) or not crossref_title:
        return "unavailable"
    return "agree" if normalize_title(openalex_title) == normalize_title(crossref_title) else "disagree"


DATE_PRECISION = ("year", "month", "day")


def _date_parts(value: str | None) -> tuple[int, ...]:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}(-\d{2}){0,2}", value.strip()):
        return ()
    return tuple(int(p) for p in value.strip().split("-"))


def date_comparison(openalex_date: str | None, crossref_date: str | None) -> tuple[str, str | None]:
    """Compare two dates only as far as both sources actually went.

    Returns (status, precision). A year-only Crossref date against a full
    OpenAlex date is compared on the year alone and says so; it is never
    expanded to a month and day nobody asserted.
    """
    a, b = _date_parts(openalex_date), _date_parts(crossref_date)
    depth = min(len(a), len(b))
    if depth == 0:
        return "unavailable", None
    return ("agree" if a[:depth] == b[:depth] else "disagree"), DATE_PRECISION[depth - 1]


def _normalize_venue(value: str) -> str:
    """Casefold, drop a leading "the" article, then strip all punctuation.

    The leading article is stripped as a whole word before punctuation
    removal, so "The Journal" and "Journal" compare equal without also
    mangling a title that merely starts with those letters, like "Theory".
    """
    value = re.sub(r"^the\b\s*", "", value.strip().casefold())
    return re.sub(r"[^a-z0-9]", "", value)


def _dict_get(value, key):
    return value.get(key) if isinstance(value, dict) else None


def europepmc_work_fields(result: dict) -> dict:
    """Extract title, venue and date fields from one Europe PMC result.

    Tolerates a missing or non-dict `journalInfo` (or `journalInfo.journal`)
    rather than raising, since a harvested payload may carry either the
    `resultType=core` or the older "lite" shape.
    """
    journal_info = _dict_get(result, "journalInfo")
    journal = _dict_get(journal_info, "journal")

    title = result.get("title")
    title = title.strip() if isinstance(title, str) else None

    venue = _dict_get(journal, "title") or result.get("journalTitle")
    venue_short = _dict_get(journal, "medlineAbbreviation") or _dict_get(journal, "isoabbreviation")

    publication_date = (
        result.get("firstPublicationDate")
        or _dict_get(journal_info, "printPublicationDate")
    )
    if not publication_date:
        pub_year = result.get("pubYear")
        publication_date = str(pub_year) if pub_year else None

    return {
        "doi": result.get("doi"),
        "title": title or None,
        "venue": venue,
        "venue_short": venue_short,
        "publication_date": publication_date,
    }


def _insert_europepmc_assertions(conn, results: list[tuple[str, dict]]) -> int:
    """Join stored Europe PMC search results to the corpus by normalized DOI.

    Runs after every OpenAlex work is in place, so a result whose DOI is not
    (yet, or ever) in the corpus is simply dropped rather than stored dangling.
    """
    doi_to_work: dict[str, str] = {}
    for row in conn.execute("SELECT id, doi FROM work"):
        doi = _normalized_doi(row["doi"])
        if doi:
            doi_to_work.setdefault(doi, row["id"])

    count = 0
    for raw_sha, result in results:
        fields = europepmc_work_fields(result)
        wid = doi_to_work.get(_normalized_doi(fields["doi"]))
        if not wid:
            continue
        conn.execute(
            "INSERT INTO europepmc_work_assertion("
            "  work_id, raw_sha, title, venue, venue_short, publication_date) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(work_id, raw_sha) DO UPDATE SET "
            "title=excluded.title, venue=excluded.venue, venue_short=excluded.venue_short, "
            "publication_date=excluded.publication_date",
            (
                wid,
                raw_sha,
                fields["title"],
                fields["venue"],
                fields["venue_short"],
                fields["publication_date"],
            ),
        )
        count += 1
    return count


def venue_comparison_status(
    openalex_venue: str | None, crossref_venue: str | None, crossref_short: str | None
) -> str:
    """Compare OpenAlex's source name against Crossref's venue assertion.

    Agreement counts against either the long or short Crossref container
    title, so a journal abbreviation is not reported as a contradiction.
    """
    if not openalex_venue or not (crossref_venue or crossref_short):
        return "unavailable"
    normalized = _normalize_venue(openalex_venue)
    candidates = {_normalize_venue(v) for v in (crossref_venue, crossref_short) if v}
    return "agree" if normalized in candidates else "disagree"


# Crossref and OpenAlex use different, overlapping type vocabularies. Only
# pairs listed here are comparable; an unmapped Crossref type is not evidence
# of a defect, so it is `incomparable`, never `disagree`.
CROSSREF_TO_OPENALEX_TYPE = {
    "journal-article": "article",
    "proceedings-article": "article",
    "posted-content": "preprint",
    "book-chapter": "book-chapter",
    "report": "report",
    "dataset": "dataset",
    "book": "book",
    "monograph": "book",
    "peer-review": "peer-review",
}


def work_type_comparison_status(openalex_type: str | None, crossref_type: str | None) -> str:
    if not openalex_type or not crossref_type:
        return "unavailable"
    expected = CROSSREF_TO_OPENALEX_TYPE.get(crossref_type)
    if expected is None:
        return "incomparable"
    return "agree" if expected == openalex_type else "disagree"


def combined_comparison_status(statuses: list[str]) -> str:
    """Fold several per-assertion comparison statuses into one.

    `unavailable` when none of them is comparable (a work with no Crossref
    assertion is the same case as one whose only assertions are
    `incomparable`), `agree` when every comparable one agrees, `disagree`
    otherwise -- so a single dissenting Crossref envelope is enough to flag
    the work even if another one agrees.
    """
    comparable = [s for s in statuses if s not in ("unavailable", "incomparable")]
    if not comparable:
        return "unavailable"
    return "agree" if all(s == "agree" for s in comparable) else "disagree"


def score_quality(conn) -> dict[str, int]:
    """Flag work records that contradict themselves. Nothing is deleted."""
    bands = {quality.COMPLETE: 0, quality.PARTIAL: 0, quality.SUSPECT: 0}
    for row in conn.execute(
        "SELECT w.id, w.title, w.doi, w.year, w.referenced_count, w.cited_by_count,"
        "       w.type, w.source_name,"
        "       (SELECT COUNT(*) FROM authorship a WHERE a.work_id = w.id) AS n_authors"
        "  FROM work w"
    ):
        assertions = conn.execute(
            "SELECT venue, venue_short, work_type FROM crossref_work_assertion "
            "WHERE work_id = ? ORDER BY raw_sha",
            (row["id"],),
        ).fetchall()
        venue_status = combined_comparison_status(
            [venue_comparison_status(row["source_name"], a["venue"], a["venue_short"]) for a in assertions]
        )
        work_type_status = combined_comparison_status(
            [work_type_comparison_status(row["type"], a["work_type"]) for a in assertions]
        )
        band, evidence = quality.assess(
            title=row["title"],
            doi=row["doi"],
            year=row["year"],
            n_authors=row["n_authors"],
            referenced_count=row["referenced_count"],
            cited_by_count=row["cited_by_count"],
            venue_status=venue_status,
            work_type_status=work_type_status,
        )
        bands[band] += 1
        conn.execute(
            "UPDATE work SET quality = ?, quality_evidence = ? WHERE id = ?",
            (band, quality.encode_evidence(evidence), row["id"]),
        )
    return bands


def score_identities(conn) -> dict[str, int]:
    bands = {identity.HIGH: 0, identity.MEDIUM: 0, identity.LOW: 0}
    for row in conn.execute("SELECT id, orcid FROM author"):
        aid = row["id"]
        names = [
            r["raw_name"]
            for r in conn.execute(
                "SELECT raw_name FROM authorship WHERE author_id = ?", (aid,)
            )
            if r["raw_name"]
        ]
        insts = [
            (r["institution_id"], r["year"])
            for r in conn.execute(
                "SELECT institution_id, year FROM affiliation WHERE author_id = ?", (aid,)
            )
        ]
        fields = [
            r["field"]
            for r in conn.execute(
                "SELECT t.field FROM authorship a "
                "JOIN work_topic wt ON wt.work_id = a.work_id "
                "JOIN topic t ON t.id = wt.topic_id WHERE a.author_id = ?",
                (aid,),
            )
            if r["field"]
        ]
        n = conn.execute(
            "SELECT COUNT(*) c FROM authorship WHERE author_id = ?", (aid,)
        ).fetchone()["c"]
        band, evidence = identity.assess(
            orcid=row["orcid"],
            raw_names=names,
            institution_years=insts,
            topic_fields=fields,
            works_in_corpus=n,
        )
        bands[band] += 1
        conn.execute(
            "UPDATE author SET confidence = ?, confidence_evidence = ? WHERE id = ?",
            (band, identity.encode_evidence(evidence), aid),
        )
    return bands


def main() -> int:
    if not RAW.exists() or not any(RAW.rglob("*.json")):
        print("no raw payloads: run `python3 harvest.py` first", file=sys.stderr)
        return 1
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = connect(DB_PATH)
    now_year = datetime.now(timezone.utc).year

    print("== loading raw payloads")
    stats = load(conn)
    print(f"   {stats['payloads']} payloads -> {stats['works']} works, "
          f"{stats['authors']} author records, {stats['authorships']} authorships, "
          f"{stats['citations']} in-corpus citations, "
          f"{stats['crossref_assertions']} crossref work assertions, "
          f"{stats['europepmc_assertions']} europepmc work assertions")

    print("== co-authorship")
    edges = graph.build_coauthorship(conn, now_year)
    print(f"   {edges} weighted edges")

    print("== work record quality")
    wbands = score_quality(conn)
    print(f"   complete={wbands['complete']} partial={wbands['partial']} suspect={wbands['suspect']}")

    print("== identity confidence")
    bands = score_identities(conn)
    print(f"   high={bands['high']} medium={bands['medium']} low={bands['low']}")

    set_meta(conn, "derived_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    set_meta(conn, "stats", {**stats, "coauthor_edges": edges, "identity": bands, "quality": wbands})
    conn.commit()
    print(f"== wrote {DB_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
