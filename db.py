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

CREATE TABLE IF NOT EXISTS institution (
  id           TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  ror          TEXT,
  country_code TEXT,
  type         TEXT
);

CREATE TABLE IF NOT EXISTS topic (
  id           TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  field        TEXT,
  domain       TEXT
);

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
-- JSON array of the indexes that assert this edge; an edge asserted by two
-- independent indexes is stronger evidence than one asserted by OpenAlex alone,
-- and the reader is shown which.
CREATE TABLE IF NOT EXISTS citation (
  citing_id TEXT NOT NULL REFERENCES work(id),
  cited_id  TEXT NOT NULL REFERENCES work(id),
  sources   TEXT NOT NULL DEFAULT '["openalex"]',
  PRIMARY KEY (citing_id, cited_id)
);
CREATE INDEX IF NOT EXISTS citation_cited ON citation(cited_id);

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

CREATE TABLE IF NOT EXISTS corpus_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
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
