#!/usr/bin/env python3
"""SQLite schema for the corpus.

The database is gitignored and never in CI -- what readers are served is the
committed JSON that `export_json.py` writes, the same split `was-it-true` and
`pubfig-content` use. A gate that needed this file would need the network and a
harvest, and a builder has neither.

One rule the schema enforces rather than documents: every renderable row names
the raw payload it came from. `work.raw_sha` and `author.raw_sha` are NOT NULL
and reference `raw_payload`, so there is no way to insert a work the site could
render without also having stored the bytes it came from. That is the
"every number traces to a stored raw payload and a source link" rule made
structural instead of aspirational.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "whocitedit.db"

SCHEMA = """
PRAGMA foreign_keys = ON;

-- Provenance. Written by the harvester, read by everything that renders.
CREATE TABLE IF NOT EXISTS raw_payload (
  sha256      TEXT PRIMARY KEY,
  url         TEXT NOT NULL,
  fetched_at  TEXT NOT NULL,
  path        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work (
  id              TEXT PRIMARY KEY,
  doi             TEXT,
  title           TEXT NOT NULL,
  year            INTEGER,
  publication_date TEXT,
  type            TEXT,
  source_id       TEXT,
  source_name     TEXT,
  is_oa           INTEGER NOT NULL DEFAULT 0,
  oa_status       TEXT,
  oa_url          TEXT,
  oa_license      TEXT,
  -- NULL whenever `abstract_reason` is not 'rendered'. See licensing.py: an
  -- abstract present in the payload is not permission to republish it.
  --
  -- THIS USED TO BE A COMMENT AND THE COMMENT WAS NOT TRUE. `test_pipeline.py`
  -- put text in this column with a `no-open-licence` reason beside it -- which
  -- is what any second writer, a backfill or a second metadata source would do
  -- by accident -- and the text went through the exporter and onto a rendered
  -- page. A licence rule that lives only in the code that happens to write the
  -- row is not a rule. The CHECK makes the leak impossible to store, and
  -- export_json refuses it a second time on the way out.
  abstract        TEXT,
  abstract_reason TEXT NOT NULL,
  cited_by_count  INTEGER NOT NULL DEFAULT 0,
  referenced_count INTEGER NOT NULL DEFAULT 0,
  -- 1 when the work came from the seed query, 0 when it was pulled in because
  -- something in the seed cited it. The reader is told which, because a
  -- neighbour has not been through the same selection as a seed.
  is_seed         INTEGER NOT NULL DEFAULT 0,
  -- Written by quality.py, the sibling of the author confidence band. Never
  -- used to delete or correct a row: a `suspect` record stays visible and says
  -- what is wrong with it.
  quality         TEXT,
  quality_evidence TEXT,
  raw_sha         TEXT NOT NULL REFERENCES raw_payload(sha256),
  -- A table-level constraint, which is where SQLite requires it: a CHECK placed
  -- among the column definitions is a syntax error at the NEXT column.
  CHECK (abstract IS NULL OR abstract_reason = 'rendered')
);
CREATE INDEX IF NOT EXISTS work_year ON work(year);
CREATE INDEX IF NOT EXISTS work_cited ON work(cited_by_count DESC);

CREATE TABLE IF NOT EXISTS work_payload (
  work_id TEXT NOT NULL REFERENCES work(id),
  raw_sha TEXT NOT NULL REFERENCES raw_payload(sha256),
  PRIMARY KEY (work_id, raw_sha)
);
CREATE INDEX IF NOT EXISTS work_payload_sha ON work_payload(raw_sha);

-- A corpus can have several independently selected fields.  Keep their
-- reviewable definitions normalized under stable keys, then associate source
-- works with every field observation that selected them.
CREATE TABLE IF NOT EXISTS corpus_field (
  key        TEXT PRIMARY KEY,
  definition TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work_corpus_field (
  work_id   TEXT NOT NULL REFERENCES work(id),
  field_key TEXT NOT NULL REFERENCES corpus_field(key),
  PRIMARY KEY (work_id, field_key)
);
CREATE INDEX IF NOT EXISTS work_corpus_field_field ON work_corpus_field(field_key);

CREATE TABLE IF NOT EXISTS author (
  id             TEXT PRIMARY KEY,
  display_name   TEXT NOT NULL,
  orcid          TEXT,
  works_count    INTEGER NOT NULL DEFAULT 0,
  cited_by_count INTEGER NOT NULL DEFAULT 0,
  -- Written by identity.py. Never used to merge two rows: a low confidence
  -- means the page says so, not that the row disappears.
  confidence     TEXT,
  confidence_evidence TEXT,
  raw_sha        TEXT REFERENCES raw_payload(sha256)
);

CREATE TABLE IF NOT EXISTS author_payload (
  author_id TEXT NOT NULL REFERENCES author(id),
  raw_sha   TEXT NOT NULL REFERENCES raw_payload(sha256),
  PRIMARY KEY (author_id, raw_sha)
);
CREATE INDEX IF NOT EXISTS author_payload_sha ON author_payload(raw_sha);

CREATE TABLE IF NOT EXISTS institution (
  id           TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  ror          TEXT,
  country_code TEXT,
  type         TEXT,
  raw_sha      TEXT REFERENCES raw_payload(sha256)
);

CREATE TABLE IF NOT EXISTS topic (
  id           TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  field        TEXT,
  domain       TEXT,
  raw_sha      TEXT REFERENCES raw_payload(sha256)
);

-- An entity can be described by more than one raw response. Keep every
-- contributor rather than letting the last response hide the earlier one.
CREATE TABLE IF NOT EXISTS institution_payload (
  institution_id TEXT NOT NULL REFERENCES institution(id),
  raw_sha        TEXT NOT NULL REFERENCES raw_payload(sha256),
  PRIMARY KEY (institution_id, raw_sha)
);
CREATE INDEX IF NOT EXISTS institution_payload_sha ON institution_payload(raw_sha);

CREATE TABLE IF NOT EXISTS topic_payload (
  topic_id TEXT NOT NULL REFERENCES topic(id),
  raw_sha  TEXT NOT NULL REFERENCES raw_payload(sha256),
  PRIMARY KEY (topic_id, raw_sha)
);
CREATE INDEX IF NOT EXISTS topic_payload_sha ON topic_payload(raw_sha);

CREATE TABLE IF NOT EXISTS authorship (
  work_id         TEXT NOT NULL REFERENCES work(id),
  author_id       TEXT NOT NULL REFERENCES author(id),
  ordinal         INTEGER NOT NULL,
  author_position TEXT,
  raw_name        TEXT,
  is_corresponding INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (work_id, author_id)
);
CREATE INDEX IF NOT EXISTS authorship_author ON authorship(author_id);

CREATE TABLE IF NOT EXISTS affiliation (
  author_id      TEXT NOT NULL REFERENCES author(id),
  institution_id TEXT NOT NULL REFERENCES institution(id),
  work_id        TEXT NOT NULL REFERENCES work(id),
  year           INTEGER,
  PRIMARY KEY (author_id, institution_id, work_id)
);

CREATE TABLE IF NOT EXISTS work_topic (
  work_id  TEXT NOT NULL REFERENCES work(id),
  topic_id TEXT NOT NULL REFERENCES topic(id),
  score    REAL,
  PRIMARY KEY (work_id, topic_id)
);

-- One row per directed citation, both ends inside the corpus. `sources` is a
-- JSON array derived from `citation_assertion`: an edge asserted by two
-- independent indexes is stronger evidence than one asserted by OpenAlex
-- alone, and the reader is shown which. The column is unconstrained TEXT with
-- DEFAULT '["openalex"]' — no CHECK constraint and no lookup table — so a new
-- source name needs no migration, only a derive.py change that unions it in.
CREATE TABLE IF NOT EXISTS citation (
  citing_id TEXT NOT NULL REFERENCES work(id),
  cited_id  TEXT NOT NULL REFERENCES work(id),
  sources   TEXT NOT NULL DEFAULT '["openalex"]',
  PRIMARY KEY (citing_id, cited_id)
);
CREATE INDEX IF NOT EXISTS citation_cited ON citation(cited_id);

-- The stored payload that made each source's claim about a citation edge.
-- There is one deterministic payload hash per source-edge pair; derive.py
-- selects the lexicographically first when duplicate payloads make the same
-- assertion. The composite foreign key makes an assertion impossible without
-- its in-corpus citation edge.
CREATE TABLE IF NOT EXISTS citation_assertion (
  citing_id TEXT NOT NULL,
  cited_id  TEXT NOT NULL,
  source    TEXT NOT NULL,
  raw_sha   TEXT NOT NULL REFERENCES raw_payload(sha256),
  PRIMARY KEY (citing_id, cited_id, source),
  FOREIGN KEY (citing_id, cited_id) REFERENCES citation(citing_id, cited_id)
);
CREATE INDEX IF NOT EXISTS citation_assertion_raw_sha ON citation_assertion(raw_sha);

-- Undirected, stored once with a_id < b_id so a pair cannot be double counted.
-- Weight is not a raw co-authorship count: see graph.py.
CREATE TABLE IF NOT EXISTS coauthorship (
  a_id       TEXT NOT NULL REFERENCES author(id),
  b_id       TEXT NOT NULL REFERENCES author(id),
  works      INTEGER NOT NULL,
  first_year INTEGER,
  last_year  INTEGER,
  weight     REAL NOT NULL,
  PRIMARY KEY (a_id, b_id),
  CHECK (a_id < b_id)
);
CREATE INDEX IF NOT EXISTS coauthorship_b ON coauthorship(b_id);

-- Crossref is an additive observation, never a replacement for the OpenAlex
-- `work` row: nothing here corrects or deletes a record, it only records what
-- Crossref separately asserted about the same DOI for a later comparison.
CREATE TABLE IF NOT EXISTS crossref_work_assertion (
  work_id    TEXT NOT NULL REFERENCES work(id),
  raw_sha    TEXT NOT NULL REFERENCES raw_payload(sha256),
  venue      TEXT,
  venue_short TEXT,
  work_type  TEXT,
  -- Plain text, markup stripped, otherwise as asserted: normalization happens
  -- only at comparison time so the reader sees what Crossref actually said.
  title      TEXT,
  -- Kept at the precision Crossref supplied ("2020", "2020-03", "2020-03-15").
  -- A year-only date is never padded to January 1st; that would invent a
  -- disagreement (or an agreement) the source never asserted.
  published  TEXT,
  PRIMARY KEY (work_id, raw_sha)
);
CREATE INDEX IF NOT EXISTS crossref_work_assertion_work ON crossref_work_assertion(work_id);

-- Europe PMC is an additive observation, never a replacement for the OpenAlex
-- `work` row: nothing here corrects or deletes a record, it only records what
-- Europe PMC separately asserted about the same DOI for a later comparison.
CREATE TABLE IF NOT EXISTS europepmc_work_assertion (
  work_id          TEXT NOT NULL REFERENCES work(id),
  raw_sha          TEXT NOT NULL REFERENCES raw_payload(sha256),
  title            TEXT,
  venue            TEXT,
  venue_short      TEXT,
  publication_date TEXT,
  PRIMARY KEY (work_id, raw_sha)
);
CREATE INDEX IF NOT EXISTS europepmc_work_assertion_work ON europepmc_work_assertion(work_id);

CREATE TABLE IF NOT EXISTS corpus_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # The committed database is generated from scratch, but this keeps a
    # locally cached database usable after the schema grows.
    for table in ("institution", "topic"):
        columns = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if "raw_sha" not in columns:
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN raw_sha TEXT REFERENCES raw_payload(sha256)"
            )
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(crossref_work_assertion)")}
    for column in ("title", "published"):
        if column not in columns:
            conn.execute(f"ALTER TABLE crossref_work_assertion ADD COLUMN {column} TEXT")
    return conn


def set_meta(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        "INSERT INTO corpus_meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )


def get_meta(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM corpus_meta WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def pair(a: str, b: str) -> tuple[str, str]:
    """Order an undirected pair so `coauthorship`'s CHECK holds."""
    return (a, b) if a < b else (b, a)
