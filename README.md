# Who Cited It

A static, crawlable graph of open scholarship: one page per paper, one per
author, each carrying its citation neighbourhood and collaboration network as
SVG solved at build time rather than simulated in the browser.

    harvest.py   OpenAlex  ->  harvest/raw/    verbatim payloads, content-addressed
    derive.py    raw       ->  whocitedit.db   normalized SQLite (gitignored)
    export_json  db        ->  web/data/       committed, sharded JSON
    render.py    web/data  ->  web/site/       9,910 static pages in ~1.3s

The boundary that matters is `web/data/`. Everything upstream needs the network
and a metered credit budget; everything downstream is a static build over files
already in the repo. **The gate never crosses it**, which is why CI is hermetic.

## Run it

```bash
./tools/ci-setup.sh                       # a venv; there are no dependencies
./tools/check.sh                          # the gate: tests + corpus floor + render
python3 -m http.server 8000 --directory web/site
```

To refresh the corpus (network, operator only):

```bash
WHOCITEDIT_MAILTO=you@example.com python3 harvest.py all
python3 derive.py && python3 export_json.py && python3 render.py
```

`corpus.json` is the committed definition of what the site covers — the filter,
the sort and the bound. Changing it changes the corpus, which is why it is not
a builder-editable file.

## The two things this site does that others do not

**It shows how confident it is that an author record is one person.** Author
records in every open bibliographic database come out of a disambiguation
algorithm that splits one researcher across several records and merges several
into one. Nothing here is ever merged, split or dropped; each author page
carries a confidence band and the signals behind it. About a third of the
current corpus is marked low confidence, and saying so is the point.

**It is static and free.** The graph is in the markup, so it renders with
JavaScript off, it is in the page a crawler sees, and there is no login and no
monthly graph allowance.

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
