# Decisions of record

This file is in `policy.deny_paths`. It records decisions that were made once,
with a reason, and that a ticket should not quietly reverse.

## The corpus is bounded, and the bound is committed

`corpus.json` names the filter, the sort and the maximum. Widening it is an
operator action, not a ticket, because the corpus definition is the answer to
"why is this paper here and not that one" and it should change deliberately.

Rejected: mirroring the OpenAlex snapshot. It is ~330 GB compressed and ~1.6 TB
expanded, against 13–16 GB free on this fleet's two Linux hosts. Measured
2026-09-03.

## The harvest is not a builder step

It needs the network, a metered credit budget and a residential IP. Builders
work against `web/data/`. This is what makes the gate hermetic, and it means a
bad day at OpenAlex cannot turn into a red board.

## Nothing is ever merged, split or dropped

Author identity is inferred by an algorithm upstream of us. We report a
confidence band and the evidence, and leave the record as the source publishes
it. "Resolve every author to one true record" is not an achievable acceptance
criterion and a ticket that claims to close it is wrong.

The bands are `high` / `medium` / `low` and their sentences live once in
`identity.py`, shipped into `corpus.json` as data so the renderer never keeps a
second copy that can drift.

## Abstracts are gated on a licence, and the gate is structural

`licensing.py` holds a closed allow-list. An unrecognised licence fails toward
withholding. The `work` table carries
`CHECK (abstract IS NULL OR abstract_reason = 'rendered')` and `export_json.py`
refuses a second time on the way out.

That CHECK exists because the rule was a comment first and the comment was not
true: `test_pipeline.py` staged a row with text beside a withholding reason —
which is what any second writer or backfill would do by accident — and the text
went through the exporter and onto a rendered page. A licence rule that lives
only in the code that happens to write the row is not a rule.

## Collaboration weight is a claim, not a measurement

Shared work count is not the ranking. Weight multiplies team size
(`1 / log2(n+1)`), author position (both lead 1.0, one lead 0.6, neither 0.3)
and recency (ten-year half-life). This is a claim about what collaboration
means; `/methodology` states it so a reader can disagree.

## The renderer is Python, and that is deliberate

Two measured reasons, both recorded here so the decision is not re-litigated:

1. The site is 9,910 pages and is meant to grow. `render.py` writes all of them
   in ~1.3 seconds. A Next.js static export of that many pages runs into
   minutes, and `demo.serve` has to build AND answer a port inside swarmward's
   90-second capture budget — a miss there produces a `skipped` line in the pull
   request, which reads exactly like a repo with no UI in it.
2. Node majors have cost this fleet real board-days. fund-tape's charter records
   sixty-four consecutive setup failures in one day from an `npm ci` guard;
   was-it-true's CI carries a comment explaining that its own `.nvmrc` claim was
   false for a month. Both repos produce static HTML. A renderer with no
   dependency tree cannot have that failure, and the gate then runs identically
   on a Linux host, a Mac host and a GitHub runner.

What this gives up is a component model and client-side routing. This site needs
neither: every page is precomputed and the only interactivity is a search box
over an index file.

## Known upstream data defects, not our bugs

Recorded 2026-09-03 from the first harvest, and not yet surfaced on the site:

- Two works carry implausible citation counts with DOIs that do not match their
  titles — `W4385245566` (79,071 citations, DOI `10.4230/lipics.itp.2023.19`)
  and `W2896457183` (46,036, DOI `10.4230/lipics.cosit.2022.18`). Both are
  Schloss Dagstuhl LIPIcs records whose titles belong to different papers.
- Seven works carry no title at all. `derive.py` renders those as
  "[No title in the source record — <source>]" rather than "Untitled", because
  the gap is the source's and the page should say so.

Extending the honesty layer from authors to works — flagging a record whose
title and DOI disagree, or whose citation count is a extreme outlier for its
year and venue — is the natural next piece of work, and it is the same product
argument as the author confidence band.
