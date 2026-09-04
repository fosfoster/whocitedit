#!/usr/bin/env python3
"""Render the site from `web/data/`. No network, no Node, no framework.

WHY THIS IS PYTHON AND NOT NEXT.JS, which is what the other content boards in
this fleet use. Two measured reasons, both specific to this corpus rather than
general preferences.

1. PAGE COUNT. This site is 9,910 pages at 3,000 works, and the corpus is meant
   to grow. A Next static export runs its per-page pipeline on every one of
   them; at the tens of milliseconds a page that costs, the build is minutes.
   `demo.serve` in the charter has to build the site AND answer a port inside
   swarmward's 90-second capture budget, so a five-minute build does not
   produce a screenshot -- it produces "never listened within 90s", which reads
   like a repo with no UI in it. This renderer does the whole site in seconds.

2. NODE MAJORS HAVE COST THIS FLEET REAL BOARD-DAYS. fund-tape's charter carries
   a paragraph about `npm ci` exiting 1 before installing anything and the board
   producing sixty-four consecutive setup failures in a day; was-it-true's CI
   pins `node-version-file` with a comment explaining that its own claim was
   false for a month. Both are Node-version problems in repos whose actual
   output is static HTML. A renderer with no dependencies cannot have them, and
   the gate then runs identically on a Linux build host, a Mac build host and a
   GitHub runner.

What this gives up is a component model and client-side routing, and this site
needs neither: every page is precomputed, the graphs are server-rendered SVG,
and the only interactivity is a search box over an index file.
"""
from __future__ import annotations

import html
import json
import math
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "web" / "data"
SITE = ROOT / "web" / "site"
ASSETS = ROOT / "web" / "assets"

SITE_NAME = "Who Cited It"
SITE_URL = "https://whocitedit.com"
TAGLINE = "The citation and collaboration graph of open research, drawn and linked to its sources."


def e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def num(n) -> str:
    return f"{n:,}" if isinstance(n, int) else str(n or "")



def _display(path: Path) -> str:
    """Repo-relative when it can be, absolute otherwise.

    `Path.relative_to` raises rather than falling back, so a progress line
    crashed the run whenever the output directory was pointed somewhere else --
    which is exactly what the pipeline test does.
    """
    try:
        return str(path.relative_to(Path(__file__).parent))
    except ValueError:
        return str(path)

def load(name: str):
    return json.loads((DATA / name).read_text())


# -- chrome ---------------------------------------------------------------

def page(*, title: str, description: str, body: str, path: str, extra_head: str = "",
         island: bool = False) -> str:
    canonical = f"{SITE_URL}/{path}".rstrip("/") or SITE_URL
    depth = path.count("/")
    root = "../" * depth or "./"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(canonical)}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:type" content="website">
<link rel="stylesheet" href="{root}assets/style.css">
{extra_head}
</head>
<body>
<header class="site"><div class="wrap">
  <a class="brand" href="{root}">{SITE_NAME}</a>
  <nav>
    <a href="{root}works/">Papers</a>
    <a href="{root}authors/">Authors</a>
    <a href="{root}methodology/">Methodology</a>
  </nav>
</div></header>
<main class="wrap">
{body}
</main>
{'<script src="' + root + 'assets/islands.js" defer></script>' if island else ''}
<footer class="site"><div class="wrap">
  <p>Built from <a href="https://openalex.org">OpenAlex</a>, which publishes its data under CC0.
     Every figure on this site links to the stored payload it came from.
     Author identity is inferred, not asserted &mdash; see <a href="{root}methodology/">methodology</a>.</p>
</div></footer>
</body>
</html>
"""


def write(path: str, content: str) -> int:
    out = SITE / path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content)
    return len(content)


# -- graph ----------------------------------------------------------------

def svg_graph(g: dict, href: dict[str, str], caption: str,
              *, kind: str = "citation", focus: str = "",
              href_prefix: str = "../") -> str:
    """Inline SVG from coordinates solved at export time.

    No <script>: the graph is in the markup, so it renders with JavaScript off,
    it is in the page a crawler sees, and it cannot shift between readers.
    """
    if not g or len(g.get("nodes") or []) < 2:
        return ""
    pos = {n["id"]: (n["x"], n["y"]) for n in g["nodes"]}
    maxc = max((n.get("cited") or n.get("works") or 1) for n in g["nodes"]) or 1

    lines = []
    for edge in g.get("edges", []):
        a, b = pos.get(edge["s"]), pos.get(edge["t"])
        if not a or not b:
            continue
        cls = "edge inner" if edge.get("inner") else "edge"
        w = 0.6 + min(edge.get("w", 1.0), 3.0) * 0.5 if "w" in edge else 1.0
        lines.append(
            f'<line class="{cls}" x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" '
            f'stroke-width="{w:.2f}"/>'
        )

    # LABELS ARE PLACED GREEDILY AND MOST OF THEM ARE DROPPED. The first cut
    # labelled every node and the result was unreadable -- twenty paper titles
    # overprinting each other along the top edge. Labels are laid out largest
    # node first, each one kept only if its box misses every box already placed,
    # and the label can sit above or below the node. Every node keeps its full
    # title in a <title> element, so the information is still there on hover and
    # still in the markup a crawler reads.
    placed: list[tuple[float, float, float, float]] = []
    ordered = sorted(
        g["nodes"],
        key=lambda n: (n["kind"] != "focus", -(n.get("cited") or n.get("works") or 0)),
    )
    labels: dict[str, tuple[float, str]] = {}
    for n in ordered:
        label = n["label"]
        short = label if len(label) <= 30 else label[:29] + "\u2026"
        scale = (n.get("cited") or n.get("works") or 1) / maxc
        r = 11 if n["kind"] == "focus" else 5 + 11 * math.sqrt(max(scale, 0.0))
        half = len(short) * 2.7
        for dy in (-r - 5, r + 11):
            top = n["y"] + dy - 9
            box = (n["x"] - half, top, n["x"] + half, top + 12)
            if not any(
                box[0] < q[2] and q[0] < box[2] and box[1] < q[3] and q[1] < box[3]
                for q in placed
            ):
                placed.append(box)
                labels[n["id"]] = (n["y"] + dy, short)
                break

    nodes = []
    for n in g["nodes"]:
        x, y = n["x"], n["y"]
        scale = (n.get("cited") or n.get("works") or 1) / maxc
        r = 11 if n["kind"] == "focus" else 5 + 11 * math.sqrt(max(scale, 0.0))
        tip = n["label"]
        if n.get("year"):
            tip += f" ({n['year']})"
        if n.get("works"):
            tip += f" \u2014 {n['works']} shared work(s)"
        target = href.get(n["id"])
        text = ""
        if n["id"] in labels:
            ly, short = labels[n["id"]]
            # A centred label on a node near the edge runs outside the viewBox
            # and is clipped mid-word. Anchor inward once the box would cross a
            # boundary; the placement pass above already reserved the space.
            half = len(short) * 2.7
            if x - half < 4:
                anchor, lx = "start", 4
            elif x + half > g["width"] - 4:
                anchor, lx = "end", g["width"] - 4
            else:
                anchor, lx = "middle", x
            text = (
                f'<text class="node-label" x="{lx}" y="{ly:.1f}" '
                f'text-anchor="{anchor}">{e(short)}</text>'
            )
        inner = f'<circle r="{r:.1f}" cx="{x}" cy="{y}"><title>{e(tip)}</title></circle>{text}'
        nodes.append(
            f'<a class="node {n["kind"]}" href="{e(target)}">{inner}</a>'
            if target
            else f'<g class="node {n["kind"]}">{inner}</g>'
        )

    # THE STATIC SVG IS THE PAGE; THE ISLAND IS AN UPGRADE. It ships in the
    # markup, so the graph is in what a crawler reads, renders with JavaScript
    # off, and is identical for every reader. `islands.js` mounts over it and
    # only then hides it -- a failed bundle leaves the page exactly as it was.
    payload = dict(g, kind=kind, focus=focus, href_prefix=href_prefix)
    # `</script>` inside a JSON string ends the block early; escaping the angle
    # bracket is the whole fix and JSON parsers read \u003c back as `<`.
    blob = json.dumps(payload, separators=(",", ":")).replace("<", "\\u003c")
    return f"""<figure class="graph" data-island="{kind}">
<div class="static-graph">
<svg viewBox="0 0 {g['width']} {g['height']}" role="img" aria-label="{e(caption)}" preserveAspectRatio="xMidYMid meet">
<g>{''.join(lines)}</g>
<g>{''.join(nodes)}</g>
</svg>
</div>
<div class="island-mount"></div>
<script type="application/json" class="graph-data">{blob}</script>
<figcaption>{caption}</figcaption>
</figure>"""


# -- evidence -------------------------------------------------------------

def badge(band, hide=None) -> str:
    """A band chip, or nothing when the band is the unremarkable one.

    A table where every row reads "complete" carries no information; the column
    is there to make the exceptions findable at a glance.
    """
    if not band or band == hide:
        return ""
    return '<span class="badge %s">%s</span>' % (e(band), e(band))


def evidence_html(evidence: list[dict], notes: dict) -> str:
    rows = []
    for item in evidence:
        signal, direction = item["signal"], item["direction"]
        template = (notes.get(signal) or {}).get(direction)
        value = item.get("value")
        if template:
            pct = f"{value:.0%}" if isinstance(value, float) else ""
            n = len(value) if isinstance(value, list) else value
            text = template.format(
                value=num(value) if isinstance(value, int) else value,
                n=n,
                pct=pct,
                doi_year=item.get("doi_year", ""),
            )
        else:
            text = f"{signal}: {value}"
        rows.append(
            f'<li><span class="dir {direction}">{direction}</span>'
            f'<span>{e(text)}</span></li>'
        )
    return f'<ul class="evidence">{"".join(rows)}</ul>'


# -- pages ----------------------------------------------------------------

def neighbour_list(w: dict, kind: str, heading: str) -> str:
    """The graph as text as well as as a picture.

    An SVG node is a link a crawler can follow but not a sentence it can read,
    and a reader with the graph collapsed on a phone still wants the list. Same
    data, same order, no second source of truth.
    """
    rows = [n for n in w["graph"]["nodes"] if n["kind"] == kind]
    if not rows:
        return ""
    rows.sort(key=lambda n: -(n.get("cited") or 0))
    items = "".join(
        f'<tr><td><a href="../{e(n["id"])}/">{e(n["label"])}</a></td>'
        f'<td class="num">{e(n.get("year") or "")}</td>'
        f'<td class="num">{num(n.get("cited") or 0)}</td></tr>'
        for n in rows
    )
    return f"""<h2 style="margin-top:26px">{heading}</h2>
<div class="scroll"><table>
  <thead><tr><th>Paper</th><th class="num">Year</th><th class="num">Cited</th></tr></thead>
  <tbody>{items}</tbody>
</table></div>"""


def bar_chart(pairs: list[tuple[int, int]], *, label: str, width: int = 980, height: int = 200) -> str:
    """Works per publication year. One series, so no legend -- the heading names it.

    Deliberately not a line: these are counts in discrete year buckets, not a
    continuous quantity sampled over time, and a line would draw slopes between
    years that mean nothing.
    """
    if not pairs:
        return ""
    pad_l, pad_b, pad_t = 4, 20, 14
    plot_h = height - pad_b - pad_t
    top = max(v for _, v in pairs) or 1
    # A 2px gap between bars, so adjacent years stay countable.
    slot = (width - pad_l * 2) / len(pairs)
    bw = max(slot - 2, 1.5)
    peak_year = max(pairs, key=lambda p: p[1])[0]
    bars, labels = [], []
    for i, (year, count) in enumerate(pairs):
        h = max((count / top) * plot_h, 1.5)
        x = pad_l + i * slot
        y = pad_t + plot_h - h
        # 4px rounded data-end, square on the baseline it is anchored to.
        r = min(4, bw / 2, h)
        bars.append(
            f'<path class="bar" d="M{x:.1f},{pad_t + plot_h:.1f} V{y + r:.1f} '
            f'q0,{-r:.1f} {r:.1f},{-r:.1f} h{bw - 2 * r:.1f} q{r:.1f},0 {r:.1f},{r:.1f} '
            f'V{pad_t + plot_h:.1f} Z">'
            f'<title>{year}: {num(count)} work(s)</title></path>'
        )
        # Direct labels only where they carry information: the two ends and the
        # peak. A number over every bar is noise, not annotation.
        if year in (pairs[0][0], pairs[-1][0], peak_year):
            labels.append(
                f'<text x="{x + bw / 2:.1f}" y="{height - 6}" text-anchor="middle">{year}</text>'
            )
            if year == peak_year:
                labels.append(
                    f'<text x="{x + bw / 2:.1f}" y="{y - 4:.1f}" text-anchor="middle">{num(count)}</text>'
                )
    return f'''<figure class="chart">
<p class="chart-title">{e(label)}</p>
<svg viewBox="0 0 {width} {height}" role="img" aria-label="{e(label)}">
  <g>{"".join(bars)}</g>
  <g class="axis">
    <line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{width - pad_l}" y2="{pad_t + plot_h}"/>
    {"".join(labels)}
  </g>
</svg>
</figure>'''


def stacked_bar(segments: list[tuple[str, int, str]], *, label: str, width: int = 470) -> str:
    """A 100% bar for a three-way split, with every segment directly labelled.

    Status colours, not series colours -- and each one carries its own word, so
    the colour never has to be read on its own.
    """
    total = sum(v for _, v, _ in segments) or 1
    height, gap = 30, 2
    x = 0.0
    rects, legend = [], []
    usable = width - gap * (len(segments) - 1)
    for name, value, tone in segments:
        w = max((value / total) * usable, 2)
        rects.append(
            f'<rect class="seg-{tone}" x="{x:.1f}" y="0" width="{w:.1f}" height="{height}" rx="3">'
            f'<title>{e(name)}: {num(value)} ({value / total:.0%})</title></rect>'
        )
        legend.append(
            f'<span><i class="legend-{tone}"></i>{e(name)} <b>{num(value)}</b> '
            f'<span class="faint">{value / total:.0%}</span></span>'
        )
        x += w + gap
    return f'''<figure class="chart">
<p class="chart-title">{e(label)}</p>
<svg viewBox="0 0 {width} {height}" role="img" aria-label="{e(label)}">{"".join(rects)}</svg>
<div class="chart-legend">{"".join(legend)}</div>
</figure>'''



def render_work(w: dict, authors: dict, titles: dict, payloads: dict,
                quality_notes: dict) -> str:
    wid = w["id"]
    q = w["quality"]
    authors_html = ", ".join(
        f'<a href="../../a/{e(a["id"])}/">{e(a["name"])}</a>'
        + (f' <span class="badge low" title="identity confidence">low</span>' if a.get("confidence") == "low" else "")
        for a in w["authors"]
    ) or '<span class="faint">No author records on this work.</span>'

    if w["abstract"]["text"]:
        abstract = f'<p>{e(w["abstract"]["text"])}</p>'
    elif w["abstract"]["reason"] == "no-open-licence":
        lic = w["oa"]["license"] or "no open licence"
        abstract = (
            f'<p class="withheld">The source holds an abstract for this work, but its '
            f'best open-access copy is under <b>{e(lic)}</b>, which does not permit us to '
            f'republish the text. Read it at the source below.</p>'
        )
    else:
        abstract = '<p class="withheld">No abstract in the source record.</p>'

    href = {n["id"]: f"../{n['id']}/" for n in w["graph"]["nodes"]}
    href[wid] = ""
    graph_caption = (
        f'{w["graph"]["shown"]} of {w["graph"]["available"]} neighbouring works in this corpus. '
        f'Blue is what this paper cites; orange is what cites it, and a dashed line '
        f'is one neighbour citing another. Only the largest labels are drawn '
        f'\u2014 every node carries its full title on hover.'
    )

    prov = payloads.get(w.get("raw") or "", {})
    rows = "".join(
        f'<tr><td>{e(t["name"])}</td><td class="faint">{e(t["field"] or "")}</td></tr>'
        for t in w["topics"]
    )
    links = []
    if w["doi"]:
        links.append(f'<a href="{e(w["doi"])}">DOI</a>')
    if w["oa"]["url"]:
        links.append(f'<a href="{e(w["oa"]["url"])}">Open access copy</a>')
    links.append(f'<a href="{e(w["openalex_url"])}">OpenAlex record</a>')

    body = f"""
<h1>{e(w["title"])}</h1>
<p class="meta">{e(w["year"] or "n.d.")}{" &middot; " + e(w["source"]["name"]) if w["source"]["name"] else ""}
   &middot; {num(w["cited_by_count"])} citations &middot; {num(w["in_corpus_cited_by"])} from inside this corpus</p>
<p>{authors_html}</p>
<div class="grid two">
<div>
  {abstract}
  {svg_graph(w["graph"], href, graph_caption, kind="citation", focus=wid, href_prefix="../")}
  <div class="legend">
    <span><i style="background:var(--focus)"></i>this paper</span>
    <span><i style="background:var(--ref)"></i>works it cites</span>
    <span><i style="background:var(--citer)"></i>works citing it</span>
    <span class="faint">node size = global citations &middot; hover for the full title</span>
  </div>
  {neighbour_list(w, "reference", "What this paper cites, inside the corpus")}
  {neighbour_list(w, "citer", "What cites it, inside the corpus")}
</div>
<div>
  <div class="panel">
    <h2>Links</h2>
    <p>{" &middot; ".join(links)}</p>
  </div>
  <div class="panel">
    <h2>Topics</h2>
    <table>{rows or '<tr><td class="faint">None recorded.</td></tr>'}</table>
  </div>
  <div class="panel">
    <h2>Is this record sound?</h2>
    <p><span class="badge {q["band"]}">{q["band"]}</span></p>
    <p>{e(q["sentence"])}</p>
    {evidence_html(q["evidence"], quality_notes)}
  </div>
  <div class="panel">
    <h2>Provenance</h2>
    <p class="meta">Everything above was read from one stored OpenAlex payload, fetched
       {e(prov.get("fetched_at", "unknown"))}.</p>
    <p class="mono faint">sha256 {e((w.get("raw") or "")[:16])}&hellip;</p>
  </div>
</div>
</div>
"""
    return page(
        title=f'{w["title"]} — {SITE_NAME}',
        description=(
            f'{w["title"]} ({w["year"] or "n.d."}) — {num(w["cited_by_count"])} citations, '
            f'its references and the papers citing it, drawn as a graph.'
        ),
        body=body,
        path=f"w/{wid}/",
        island=True,
    )


def render_author(a: dict, notes: dict, bands: dict, payloads: dict) -> str:
    band = a["confidence"]["band"]
    works_rows = "".join(
        f'<tr><td><a href="../../w/{e(w["id"])}/">{e(w["title"])}</a></td>'
        f'<td class="faint">{e(w["position"] or "")}</td>'
        f'<td class="num">{e(w["year"] or "")}</td>'
        f'<td class="num">{num(w["cited"])}</td></tr>'
        for w in a["works"]
    )
    insts = ", ".join(
        e(i["name"]) + (f' <span class="faint">({i["first_year"]}–{i["last_year"]})</span>'
                        if i.get("first_year") else "")
        for i in a["institutions"]
    ) or '<span class="faint">No institution on the works in this corpus.</span>'

    href = {n["id"]: f"../{n['id']}/" for n in a["graph"]["nodes"]}
    href[a["id"]] = ""
    caption = (
        f'{a["graph"]["shown"]} of {a["graph"]["available"]} collaborators, ranked by '
        f'collaboration weight rather than by shared-paper count. Dashed lines are '
        f'collaborations between the collaborators. See '
        f'<a href="../../methodology/">how the weight is computed</a>.'
    )

    body = f"""
<h1>{e(a["name"])}</h1>
<p class="meta">
  <span class="badge {band}">{band} confidence</span>
  &middot; {num(a["in_corpus"]["works"])} work(s) in this corpus
  &middot; {num(a["cited_by_count"])} citations across {num(a["works_count"])} works in OpenAlex
  {"&middot; ORCID " + e(a["orcid"]) if a["orcid"] else ""}
</p>
<div class="grid two">
<div>
  {svg_graph(a["graph"], href, caption, kind="collaboration", focus=a["id"], href_prefix="../")}
  <div class="legend">
    <span><i style="background:var(--focus)"></i>{e(a["name"])}</span>
    <span><i style="background:var(--ref)"></i>collaborator</span>
    <span>line weight = collaboration weight</span>
  </div>
  <h2 style="margin-top:26px">Works in this corpus</h2>
  <div class="scroll"><table>
    <thead><tr><th>Title</th><th>Position</th><th class="num">Year</th><th class="num">Cited</th></tr></thead>
    <tbody>{works_rows}</tbody>
  </table></div>
</div>
<div>
  <div class="panel">
    <h2>Is this one person?</h2>
    <p>{e(bands[band])}</p>
    {evidence_html(a["confidence"]["evidence"], notes)}
  </div>
  <div class="panel">
    <h2>Affiliations</h2>
    <p class="meta">{insts}</p>
  </div>
  <div class="panel">
    <h2>In this corpus</h2>
    <p class="meta">h-index {num(a["in_corpus"]["hindex"])} over the works held here,
       which is a number about this corpus and not about a career.</p>
    <p class="meta"><a href="{e(a["openalex_url"])}">OpenAlex record</a></p>
  </div>
</div>
</div>
"""
    return page(
        title=f'{a["name"]} — {SITE_NAME}',
        description=(
            f'{a["name"]}: collaboration graph, works in the corpus, and how confident '
            f'we are that this record describes one person ({band}).'
        ),
        body=body,
        path=f"a/{a['id']}/",
        island=True,
    )


def render_home(corpus: dict, works: list, authors: list) -> str:
    c = corpus["counts"]
    top = "".join(
        f'<tr><td><a href="w/{e(w["id"])}/">{e(w["title"])}</a>'
        f'<br><span class="meta faint">{e(", ".join(w["authors"]))}'
        f'{" and " + str(w["n_authors"] - len(w["authors"])) + " more" if w["n_authors"] > len(w["authors"]) else ""}</span></td>'
        f'<td class="num">{e(w["year"] or "")}</td><td class="num">{num(w["cited"])}</td>'
        f'<td class="num">{num(w["in_corpus_cited"])}</td></tr>'
        for w in works[:40]
    )
    ident = corpus["identity"]
    q = corpus["quality"]
    year_counts: dict[int, int] = {}
    for w in works:
        if w["year"]:
            year_counts[w["year"]] = year_counts.get(w["year"], 0) + 1
    low_pct = ident["low"] / max(sum(ident.values()), 1)
    body = f"""
<h1>{TAGLINE}</h1>
<p class="lede">{e(corpus["definition"]["description"])} Every page is precomputed and
   every graph is drawn here rather than in your browser, so there is no login,
   no per-month graph allowance and nothing to wait for.</p>
<div class="stats">
  <div><b>{num(c["works"])}</b><span>papers</span></div>
  <div><b>{num(c["authors"])}</b><span>authors</span></div>
  <div><b>{num(c["citations"])}</b><span>citation edges</span></div>
  <div><b>{num(c["coauthor_edges"])}</b><span>collaboration edges</span></div>
  <div><b>{num(c["institutions"])}</b><span>institutions</span></div>
</div>
<div class="panel">
  <h2>What this corpus is, exactly</h2>
  <p>The {num(c["works"])} most-cited works in OpenAlex's
     <b>{e(corpus["definition"]["name"])}</b> subfield, every author on them, and every
     citation between two works that are both inside the set. That bound is
     committed to the repository as <span class="mono">corpus.json</span>, so
     &ldquo;why is this paper here and not that one&rdquo; has a diffable answer.
     {num(c['works'])} is where this starts, not the shape of the thing.</p>
  <p><b>{low_pct:.0%} of author records here are marked low confidence, and
     {num(q["suspect"])} of {num(c["works"])} paper records contradict themselves.</b> Author
     identity in every open bibliographic database is produced by an algorithm that
     splits one researcher across several records and merges several researchers
     into one. We do not fix that silently. Each author page states how confident
     it is and shows you the signals, and nothing is ever merged away.
     <a href="methodology/">How that is judged</a>.</p>
</div>
<div class="grid two-even">
{bar_chart(sorted(year_counts.items()), label=f"Works by publication year ({len(year_counts)} years)")}
</div>
<div class="grid two-even">
{stacked_bar([("high", ident["high"], "good"), ("medium", ident["medium"], "warning"),
              ("low", ident["low"], "critical")],
             label="Is each author record one person?")}
{stacked_bar([("complete", q["complete"], "good"), ("partial", q["partial"], "warning"),
              ("suspect", q["suspect"], "critical")],
             label="Does each paper record agree with itself?")}
</div>

<h2>Most cited</h2>
<div class="scroll"><table>
  <thead><tr><th>Paper</th><th class="num">Year</th><th class="num">Cited</th><th class="num">In corpus</th></tr></thead>
  <tbody>{top}</tbody>
</table></div>
<p class="meta"><a href="works/">All {num(c["works"])} papers</a> &middot;
   <a href="authors/">All {num(c["authors"])} authors</a></p>
"""
    return page(title=f"{SITE_NAME} — {TAGLINE}", description=TAGLINE, body=body, path="")


def render_browse(kind: str, rows: list, corpus: dict) -> str:
    if kind == "works":
        head = ('<tr><th>Paper</th><th>Record</th><th class="num">Year</th>'
                '<th class="num">Cited</th><th class="num">In corpus</th></tr>')
        body_rows = "".join(
            f'<tr><td><a href="../w/{e(r["id"])}/">{e(r["title"])}</a>'
            f'<br><span class="meta faint">{e(", ".join(r["authors"]))}</span></td>'
            f'<td>{badge(r.get("quality"), hide="complete")}</td>' 
            f'<td class="num">{e(r["year"] or "")}</td><td class="num">{num(r["cited"])}</td>'
            f'<td class="num">{num(r["in_corpus_cited"])}</td></tr>'
            for r in rows[:400]
        )
        title, index = "Papers", "works-index.json"
    else:
        head = '<tr><th>Author</th><th>Identity</th><th class="num">Works</th><th class="num">Collaborators</th><th class="num">Cited</th></tr>'
        body_rows = "".join(
            f'<tr><td><a href="../a/{e(r["id"])}/">{e(r["name"])}</a></td>'
            f'<td><span class="badge {r["band"]}">{r["band"]}</span></td>'
            f'<td class="num">{num(r["works"])}</td><td class="num">{num(r["coauthors"])}</td>'
            f'<td class="num">{num(r["cited"])}</td></tr>'
            for r in rows[:400]
        )
        title, index = "Authors", "authors-index.json"

    body = f"""
<h1>{title}</h1>
<p class="lede">{num(len(rows))} in this corpus. The table shows the first 400; search the
   whole set below.</p>
<input type="search" id="q" placeholder="Search all {num(len(rows))} {title.lower()}&hellip;"
       data-index="../data/{index}" data-kind="{kind}" autocomplete="off">
<div class="hits" id="hits"></div>
<div class="scroll" id="table"><table><thead>{head}</thead><tbody>{body_rows}</tbody></table></div>
<script src="../assets/app.js" defer></script>
"""
    return page(
        title=f"{title} — {SITE_NAME}",
        description=f"All {num(len(rows))} {title.lower()} in the {corpus['definition']['name']} corpus.",
        body=body,
        path=f"{kind}/",
    )


def render_methodology(corpus: dict) -> str:
    abstracts = corpus["abstracts"]
    src_rows = "".join(
        f'<tr><td><a href="{e(s["url"])}">{e(s["name"])}</a></td><td>{e(s["license"])}</td>'
        f'<td>{e(s["role"])}</td></tr>'
        for s in corpus["sources"]
    )
    body = f"""
<h1>Methodology</h1>
<p class="lede">What is in this corpus, where every figure came from, and the three
   things this site refuses to do.</p>

<div class="panel">
<h2>Sources</h2>
<div class="scroll"><table>
  <thead><tr><th>Source</th><th>Licence</th><th>Used for</th></tr></thead>
  <tbody>{src_rows}</tbody>
</table></div>
<p class="meta">Nothing here is scraped from a publisher's website. Every record comes
   from an open API or bulk dump under a licence that permits reuse, and each page
   names the stored payload it was rendered from.</p>
</div>

<div class="panel">
<h2>Collaboration weight is not a count of shared papers</h2>
<p>Two people who wrote a two-author paper together last year worked together.
   Two people who appear in the middle of a 900-author collaboration paper in 1998
   probably did not. Ranking collaborators by shared-paper count treats those as
   the same fact, so this site weights each shared work by three things:</p>
<ul>
  <li><b>Team size.</b> A pair's share of a work decays as <span class="mono">1 / log2(n+1)</span>
      in the number of authors, so a small team counts for more than a roster.</li>
  <li><b>Author position.</b> Both in a lead position (first or last) counts fully;
      one lead counts 0.6; neither counts 0.3.</li>
  <li><b>Recency.</b> A ten-year half-life, so a graph shows a current network rather
      than a career total.</li>
</ul>
<p>This is a claim about what collaboration means, not a measurement. It is stated
   here so you can disagree with it.</p>
</div>

<div class="panel">
<h2>Author identity is inferred, and we show our work</h2>
<p>Author records in every open bibliographic database are produced by a
   disambiguation algorithm. It splits one researcher across several records and
   merges several researchers into one. Tools built on top of this usually render
   the output as fact.</p>
<p>Instead, every author page carries a confidence band and the signals behind it:
   whether a human-claimed ORCID is present, how many distinct name forms appear,
   how many institutions show up inside any five-year window, and how much of the
   record sits in one field. <b>No record is ever merged, split or dropped here.</b>
   A record we doubt says so and stays visible.</p>
<p class="meta">Currently {num(corpus["identity"]["high"])} high, {num(corpus["identity"]["medium"])} medium
   and {num(corpus["identity"]["low"])} low confidence.</p>
</div>

<div class="panel">
<h2>Paper records get the same treatment</h2>
<p>A work record can contradict itself, and in this corpus a surprising number do.
   We check four things that need no second source to verify: whether the record
   lists any authors at all, whether it records references behind a large citation
   count, whether the year embedded in its DOI agrees with its own publication
   year, and whether it has a title.</p>
<p class="meta">{num(corpus["quality"]["complete"])} complete &middot;
   {num(corpus["quality"]["partial"])} partial &middot;
   {num(corpus["quality"]["suspect"])} suspect.</p>
<p><b>Deliberately not checked: whether a citation count is implausible.</b>
   This corpus is selected by citation count, so every work in it is an outlier
   against the wider population, and a threshold fitted here would be fitted to
   the selection rather than to the data. Calling a number wrong needs evidence
   this tier does not carry.</p>
<p>Nothing is deleted or corrected. A record flagged
   <span class="badge suspect">suspect</span> stays on the site with its figures
   intact and a panel saying what is wrong with it &mdash; silently fixing a
   source is how a reader ends up trusting a number nobody can trace.</p>
</div>

<div class="panel">
<h2>Why some abstracts are missing</h2>
<p>An abstract present in a source record is not permission to republish it.
   Publishers have had abstracts removed from open indexes in bulk &mdash; Springer
   Nature in 2022 and Elsevier in 2024 &mdash; and the ones that remain carry the
   licence of the copy they came from. This site renders an abstract only when the
   work has an open-access copy under a licence that permits redistribution, and
   says which of the two reasons applies when it does not.</p>
<p class="meta">
   {num(abstracts.get("rendered", 0))} rendered &middot;
   {num(abstracts.get("no-open-licence", 0))} withheld for licence &middot;
   {num(abstracts.get("not-in-source", 0))} absent from the source.</p>
</div>

<div class="panel">
<h2>What this site will not do</h2>
<ul>
  <li>Scrape publisher websites, or route around a paywall.</li>
  <li>Republish text it does not hold a redistributable licence for.</li>
  <li>Merge two author records because they share a name, or hide a record because
      its identity is doubtful.</li>
  <li>Present the in-corpus graph as though it were the whole of science. Citation
      counts shown are global; the graph is explicitly the subgraph inside this
      corpus, and each page says how much of a neighbourhood it is showing.</li>
</ul>
</div>
"""
    return page(
        title=f"Methodology — {SITE_NAME}",
        description="Sources, licences, how collaboration weight is computed, and how author identity confidence is judged.",
        body=body,
        path="methodology/",
    )


# -- driver ---------------------------------------------------------------

def main() -> int:
    if not DATA.exists():
        print("no web/data: run `python3 export_json.py` first", file=sys.stderr)
        return 1
    corpus = load("corpus.json")
    works_index = load("works-index.json")
    authors_index = load("authors-index.json")
    payloads = load("payloads.json")
    notes = corpus["identity_notes"]
    bands = corpus["identity_bands"]
    quality_notes = corpus["quality_notes"]

    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True)
    shutil.copytree(ASSETS, SITE / "assets")

    n = 0
    total = 0
    titles = {w["id"]: w for w in works_index}
    author_names = {a["id"]: a["name"] for a in authors_index}

    for shard in sorted((DATA / "works").glob("*.json")):
        for wid, w in json.loads(shard.read_text()).items():
            total += write(
                f"w/{wid}/index.html",
                render_work(w, author_names, titles, payloads, quality_notes),
            )
            n += 1

    for shard in sorted((DATA / "authors").glob("*.json")):
        for aid, a in json.loads(shard.read_text()).items():
            total += write(f"a/{aid}/index.html", render_author(a, notes, bands, payloads))
            n += 1

    total += write("index.html", render_home(corpus, works_index, authors_index))
    total += write("works/index.html", render_browse("works", works_index, corpus))
    total += write("authors/index.html", render_browse("authors", authors_index, corpus))
    total += write("methodology/index.html", render_methodology(corpus))
    n += 4

    # The browse pages fetch these at runtime for search; the rest of the corpus
    # data is already baked into the HTML and is not shipped.
    (SITE / "data").mkdir(exist_ok=True)
    for name in ("works-index.json", "authors-index.json"):
        shutil.copy(DATA / name, SITE / "data" / name)

    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n")
    urls = "".join(
        f"<url><loc>{SITE_URL}/{p}</loc></url>"
        for p in ["", "works/", "authors/", "methodology/"]
        + [f"w/{w['id']}/" for w in works_index]
        + [f"a/{a['id']}/" for a in authors_index]
    )
    write("sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')

    print(f"== rendered {n} pages ({total / 1e6:.1f} MB) to {_display(SITE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
