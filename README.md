# Who Cited It

A static, crawlable graph of open scholarship: one page per paper, author,
institution, and topic, each carrying the relevant ranked lists and graphs as
SVG solved at build time rather than simulated in the browser.

    harvest.py   OpenAlex + COCI + Crossref  ->  harvest/raw/    verbatim payloads, content-addressed
    derive.py    raw       ->  whocitedit.db   normalized SQLite (gitignored)
    export_json  db        ->  web/data/       committed, sharded JSON
    render.py    web/data  ->  web/site/       static work, author, institution and topic pages
    web/app/     React     ->  web/assets/islands.js   one committed bundle

The boundary that matters is `web/data/`. Everything upstream needs the network
and a metered credit budget; everything downstream is a static build over files
already in the repo. **The gate never crosses it**, which is why CI is hermetic.

The reader flow is deliberately one-way: the database is normalized from the
stored OpenAlex payloads, `export_json.py` turns it into content-addressed,
sharded JSON (including entity indexes and aggregate payload provenance), and
`render.py` turns those shards into static HTML. Work, author, institution, and
topic detail pages are linked to one another where the corresponding shard is
present; `render.py` also writes one compact `web/site/data/search-index.json`
and gives every generated page a deferred header search. That search does not
request its local index until the reader enters a non-empty query; browse pages
continue to use their own copied collection indexes. There is no search service,
server endpoint, or Node runtime involved. A legacy
`web/data/` release without institution or topic indexes still renders its
existing pages, with empty collection browses and no dangling new detail links.
It also renders a field directory at `/fields/` and one complete static paper
browse page at `/fields/<field-key>/` for every normalized field.

## Run it

```bash
./tools/ci-setup.sh          # a venv; the gate has no dependencies and no Node
./tools/check.sh             # tests + corpus floor + bundle freshness + render
python3 -m http.server 8000 --directory web/site
```

The React islands live in `web/app/` and compile to one committed bundle. The
gate never builds them — it checks the committed bundle against a hash of its
sources — so rendering and publishing the site need Python and nothing else:

```bash
./tools/build-app.sh         # npm ci + typecheck + lint + build, then re-stamp
```

## Deploy and verify

Deploy the committed site, then verify the production response in that order:

```bash
./tools/deploy.sh
python3 check_deploy.py https://whocitedit.com
```

An exit 1 means deployed content has drifted from the expected release; an
exit 2 means `https://whocitedit.com` could not be reached. CI only runs the
checker's fixture-backed tests; its automated gate remains network-free and
never contacts production. Deployment parity checks a normalized sitemap route set
match (order- and origin-independent), the exact deterministic HTML
content for home, methodology, and one available sampled work, author,
institution, and topic route, and a SHA-256 hash of each of the three
reader-critical static assets: `web/assets/style.css`, `web/assets/app.js`,
and `web/assets/islands.js`.

To refresh the corpus (network, operator only):

```bash
WHOCITEDIT_MAILTO=you@example.com python3 harvest.py all
# A separate, bounded COCI pass stores outgoing DOI references in the same raw
# provenance store. It is never run by the builder or CI.
python3 harvest.py citations
# A separate, bounded Crossref metadata pass. It is operator-only too.
python3 harvest.py crossref
python3 derive.py && python3 export_json.py && python3 render.py
```

`corpus.json` is the committed definition of what the site covers — the filter,
the sort and the bound. Changing it changes the corpus, which is why it is not
a builder-editable file.

Corpus definitions have two compatible contract shapes. The current legacy
shape is one top-level field definition (with `name`, `seed_filter`,
`seed_sort`, `max_works`, and its other definition properties); it is
normalized under a deterministic key derived from `name` — for example,
`Artificial Intelligence` becomes `artificial-intelligence`. A multi-field
corpus uses explicit stable keys instead:

```json
{
  "fields": {
    "artificial-intelligence": {
      "name": "Artificial Intelligence",
      "seed_filter": "primary_topic.subfield.id:subfields/1702",
      "seed_sort": "cited_by_count:desc",
      "max_works": 3000
    }
  }
}
```

Harvesting paginates each normalized field independently with that field's
filter, sort, and bound. Each OpenAlex work-page observation in
`harvest/manifest.jsonl` carries its `field_key`; the content-addressed raw
payload remains unchanged by that provenance tag. Thus one raw payload (and
one work in it) may be observed in more than one field while retaining a
separate manifest line for each observation.

`export_json.py` carries that many-to-many membership into every work's
`fields` array and writes `web/data/fields-index.json`, whose rows provide the
normalized field key, name, description, and member count. `render.py` consumes
both surfaces to build `/fields/` and `/fields/<field-key>/`. A field page lists
all and only that field's exported members in `works-index.json` order; a work
that belongs to several fields appears on each relevant field page, but all of
those rows point to its single canonical `/w/<id>/` page.

The committed data release predates those two export surfaces. For that legacy
shape, the renderer derives the sole deterministic field key with
`corpus_contract.normalize` and places every indexed work in that one field.
This compatibility branch is intentionally limited to releases where both the
field index and per-work membership arrays are absent; current and future
exports retain their explicit memberships.

## The two things this site does that others do not

**It shows how confident it is that an author record is one person.** Author
records in every open bibliographic database come out of a disambiguation
algorithm that splits one researcher across several records and merges several
into one. Nothing here is ever merged, split or dropped; each author page
carries a confidence band and the signals behind it. About a third of the
current corpus is marked low confidence, and saying so is the point.

**It is static and free.** The graph is in the markup, so it renders with
JavaScript off, it is in the page a crawler sees, and there is no login and no
monthly graph allowance. React then upgrades each figure in place — drag, zoom,
hover, a citation view laid out along real time, and a year brush on a
collaboration network — and only hides the static SVG once it has mounted.

## What it will not do

Scrape publisher sites, route around a paywall, republish text it holds no
redistributable licence for, mirror the whole of OpenAlex, or present the
in-corpus subgraph as though it were the whole of science. See
`docs/direction.md` and `/methodology` on the site.

## Sources

[OpenAlex](https://openalex.org) (CC0) is the backbone: works, authors,
institutions, topics and citation edges. Its API is credit-metered at 100,000
credits a day free, where a list request costs ten; `openalex.py` counts credits
rather than requests and refuses rather than overrunning.

[OpenCitations COCI](https://opencitations.net/index/coci/) supplies a separate
operator-only DOI reference harvest. `opencitations.py` applies the same
preflight budget, retry, throttling, content-addressed raw storage, and manifest
provenance rules as the OpenAlex client; `python3 harvest.py citations` is the
only entry point that invokes it.

[Crossref](https://www.crossref.org/) supplies a separate operator-only work
metadata harvest: `python3 harvest.py crossref`. `crossref.py` makes bounded,
identified requests and retains each response under the same raw-store and
manifest rules. Its downstream metadata contract is bibliographic metadata and
provenance only: it excludes publisher scraping, abstracts, and full text.
`derive.py` joins each stored envelope to a corpus work by normalized DOI and
keeps only its venue, type, plain-text title and a publication date at the
precision Crossref gave. Work pages carry those in a title, venue and date
panel that also holds whichever of OpenAlex, Crossref and
[Europe PMC](https://europepmc.org/) asserts the same work, one labelled row
per source with that source's own payload hash and fetch time, verdicted
`agree`/`disagree`/`unavailable`; a source that asserts nothing has no row and
the OpenAlex record itself is never changed by a disagreement.

**Venue and work type as parallel observations.** A work page shows the
OpenAlex and Crossref venue and work-type assertions side by side, each
labelled by its source and carrying its own payload hash and fetch time.
Neither record is edited or merged into the other; a disagreement is shown,
not resolved. Agreement on venue counts a journal abbreviation (Crossref's
`container-title` short form) the same as the full title, so an abbreviation
is not reported as a contradiction. Work type is compared through a fixed
Crossref-to-OpenAlex vocabulary mapping; a Crossref type with no mapped
OpenAlex equivalent is reported as `incomparable`, not `disagree` — an
unmapped type pair is not evidence of a defect.
