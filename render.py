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
from urllib.parse import urlsplit

import corpus_contract
from opencitations import normalize_doi

ROOT = Path(__file__).parent
DATA = ROOT / "web" / "data"
SITE = ROOT / "web" / "site"
ASSETS = ROOT / "web" / "assets"

SITE_NAME = "Who Cited It"
SITE_URL = "https://whocitedit.com"
TAGLINE = "The citation and collaboration graph of open research, drawn and linked to its sources."


# Set once for each static build, then used by the shared page chrome.  Detail
# page renderers deliberately do not need to know which collection invoked
# them: field navigation is shared navigation, not page-specific data.
NAV_FIELDS: list[dict] = []


# OpenAlex's work types are broader than RIS's record types. These mappings use
# the more general RIS type where a work type does not have an exact equivalent.
RIS_TYPES = {
    "article": "JOUR",
    "book": "BOOK",
    "book-chapter": "CHAP",
    "book-review": "JOUR",
    "conference-abstract": "CONF",
    "conference-paper": "CONF",
    "data-paper": "JOUR",
    "dataset": "DATA",
    "dissertation": "THES",
    "editorial": "JOUR",
    "erratum": "JOUR",
    "other": "GEN",
    "paratext": "GEN",
    "preprint": "UNPB",
    "reference-entry": "GEN",
    "report": "RPRT",
    "review": "JOUR",
    "software": "COMP",
    "software-paper": "JOUR",
}


# Explicit OpenAlex work type -> schema.org @type mapping for JSON-LD.
# Anything not listed here falls back to ScholarlyArticle.
SCHEMA_TYPES = {
    "dataset": "Dataset",
    "preprint": "ScholarlyArticle",
    "book": "Book",
    "book-chapter": "Chapter",
    "dissertation": "Thesis",
    "report": "Report",
    "software": "SoftwareSourceCode",
    "other": "CreativeWork",
    "paratext": "CreativeWork",
    "reference-entry": "CreativeWork",
}


# Every exported work type -> a CSL 1.0.2 item type. CSL's vocabulary is narrower
# than OpenAlex's, so several work types share the nearest CSL type; `document` is
# CSL's own generic item type and carries anything we do not recognise.
CSL_TYPES = {
    "article": "article-journal",
    "book": "book",
    "book-chapter": "chapter",
    "book-review": "review-book",
    "conference-abstract": "paper-conference",
    "conference-paper": "paper-conference",
    "data-paper": "article-journal",
    "dataset": "dataset",
    "dissertation": "thesis",
    "editorial": "article-journal",
    "erratum": "article-journal",
    "other": "document",
    "paratext": "document",
    "preprint": "article",
    "reference-entry": "entry-encyclopedia",
    "report": "report",
    "review": "review",
    "software": "software",
    "software-paper": "article-journal",
}


def e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def num(n) -> str:
    return f"{n:,}" if isinstance(n, int) else str(n or "")


def canonical_url(path: str) -> str:
    return f"{SITE_URL}/{path}".rstrip("/") or SITE_URL


def json_ld(value: dict) -> str:
    """Serialize JSON-LD without letting data close its script element."""
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f'<script type="application/ld+json">{encoded}</script>'


def citation_tag(name: str, value) -> str:
    return f'<meta name="{e(name)}" content="{e(value)}">' if value else ""


def author_head_metadata(a: dict, canonical: str) -> str:
    """Person metadata limited to the author record's public identities."""
    person = {
        "@context": "https://schema.org",
        "@type": "Person",
        "@id": canonical,
        "url": canonical,
        "name": a["name"],
    }
    identities = []
    if a.get("openalex_url"):
        identities.append(a["openalex_url"])
    if a.get("orcid"):
        identities.append(f'https://orcid.org/{a["orcid"]}')
    if identities:
        person["sameAs"] = identities
    return json_ld(person)


def breadcrumb_json_ld(trail: list[tuple[str, str]]) -> str:
    """BreadcrumbList metadata for an ordered sequence of (name, path) crumbs."""
    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": position,
                "name": name,
                "item": canonical_url(path),
            }
            for position, (name, path) in enumerate(trail, start=1)
        ],
    }
    return json_ld(breadcrumb)


def work_head_metadata(w: dict, canonical: str) -> str:
    """Citation and CreativeWork metadata using only the exported work fields."""
    citation = [
        citation_tag("citation_title", w.get("title")),
        *[citation_tag("citation_author", author.get("name"))
          for author in w.get("authors", [])],
        citation_tag("citation_publication_date", w.get("date") or w.get("year")),
        citation_tag("citation_doi", w.get("doi")),
        citation_tag("citation_public_url", canonical),
    ]

    creative_work = {
        "@context": "https://schema.org",
        "@type": SCHEMA_TYPES.get(w.get("type"), "ScholarlyArticle"),
        "@id": canonical,
        "url": canonical,
    }
    if w.get("title"):
        creative_work["name"] = w["title"]
    if w.get("openalex_url"):
        creative_work["sameAs"] = w["openalex_url"]
    if w.get("id"):
        creative_work["identifier"] = [{
            "@type": "PropertyValue",
            "propertyID": "OpenAlex",
            "value": w["id"],
        }]
    authors = []
    for author in w.get("authors", []):
        person = {"@type": "Person"}
        if author.get("name"):
            person["name"] = author["name"]
        if author.get("id"):
            person["@id"] = canonical_url(f'a/{author["id"]}/')
            person["url"] = person["@id"]
            person["sameAs"] = f'https://openalex.org/{author["id"]}'
        if len(person) > 1:
            authors.append(person)
    if authors:
        creative_work["author"] = authors
    if w.get("date") or w.get("year"):
        creative_work["datePublished"] = str(w.get("date") or w["year"])
    if w.get("doi"):
        creative_work.setdefault("identifier", []).append({
            "@type": "PropertyValue",
            "propertyID": "DOI",
            "value": w["doi"],
        })
    source = w.get("source") or {}
    if source.get("name") or source.get("id"):
        source_work = {"@type": "CreativeWork"}
        if source.get("name"):
            source_work["name"] = source["name"]
        if source.get("id"):
            source_work["identifier"] = {
                "@type": "PropertyValue",
                "propertyID": "OpenAlex",
                "value": source["id"],
            }
        creative_work["isPartOf"] = source_work

    return "\n".join(tag for tag in citation if tag) + "\n" + json_ld(creative_work)


def institution_head_metadata(i: dict, canonical: str) -> str:
    """Organization metadata limited to the institution record's public identities."""
    org = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "@id": canonical,
        "url": canonical,
        "name": i["name"],
    }
    identities = []
    if i.get("openalex_url"):
        identities.append(i["openalex_url"])
    if (i.get("metadata") or {}).get("ror"):
        identities.append(i["metadata"]["ror"])
    if identities:
        org["sameAs"] = identities
    return json_ld(org)


def topic_head_metadata(t: dict, canonical: str) -> str:
    """DefinedTerm metadata limited to the topic record's public identities."""
    term = {
        "@context": "https://schema.org",
        "@type": "DefinedTerm",
        "@id": canonical,
        "url": canonical,
        "name": t["name"],
    }
    if t.get("openalex_url"):
        term["sameAs"] = [t["openalex_url"]]
    return json_ld(term)


def home_head_metadata(canonical: str) -> str:
    """WebSite metadata for the homepage."""
    website = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "@id": canonical,
        "url": canonical,
        "name": SITE_NAME,
        "description": TAGLINE,
        "inLanguage": "en",
    }
    return json_ld(website)


def bibtex_escape(value) -> str:
    """Escape a UTF-8 value for a braced BibTeX field."""
    escaped = []
    for char in str(value):
        escaped.append({
            "\\": r"\textbackslash{}",
            "{": r"\{",
            "}": r"\}",
            "#": r"\#",
            "$": r"\$",
            "%": r"\%",
            "&": r"\&",
            "_": r"\_",
            "~": r"\textasciitilde{}",
            "^": r"\textasciicircum{}",
        }.get(char, char))
    return "".join(escaped)


BIBTEX_TYPES = {
    "article": "@article",
    "book": "@book",
    "book-chapter": "@incollection",
    "book-review": "@article",
    "conference-abstract": "@inproceedings",
    "conference-paper": "@inproceedings",
    "data-paper": "@article",
    "dataset": "@misc",
    "dissertation": "@phdthesis",
    "editorial": "@article",
    "erratum": "@article",
    "other": "@misc",
    "paratext": "@misc",
    "preprint": "@misc",
    "reference-entry": "@incollection",
    "report": "@techreport",
    "review": "@article",
    "software": "@misc",
    "software-paper": "@article",
}


def bibtex_type(work_type) -> str:
    """The BibTeX entry type for a work's type, falling back to @misc."""
    return BIBTEX_TYPES.get(work_type, "@misc")


def work_bibtex(w: dict) -> str:
    """A small, deterministic citation from fields already rendered on a work page."""
    source = w.get("source") or {}
    authors = [author.get("name") for author in w.get("authors", []) if author.get("name")]
    fields = [
        ("author", " and ".join(authors)),
        ("title", w.get("title")),
        ("year", w.get("year")),
        ("howpublished", source.get("name")),
        ("doi", w.get("doi")),
    ]
    rendered = [f"  {name} = {{{bibtex_escape(value)}}}" for name, value in fields if value]
    body = ",\n".join(rendered)
    entry_type = bibtex_type(w.get("type"))
    return f"{entry_type}{{{w['id']},\n" + (f"{body}\n" if body else "") + "}\n"


def _csl_issued(w: dict) -> dict | None:
    """CSL ``date-parts`` from a full publication date, or the bare year."""
    date = w.get("date")
    if date:
        try:
            parts = [int(p) for p in str(date).split("-")]
        except ValueError:
            parts = []
        if len(parts) >= 2:
            return {"date-parts": [parts]}
    year = w.get("year")
    if year:
        return {"date-parts": [[year]]}
    return None


def _csl_doi(value) -> str | None:
    """A bare DOI for CSL's ``DOI`` field, or ``None`` if there is none to derive."""
    if not value:
        return None
    try:
        return normalize_doi(value)
    except ValueError:
        return None


def csl_type(value) -> str:
    """The CSL item type for an exported work type, ``document`` for anything else.

    A missing or unrecognised work type is not an error here: CSL requires every
    item to carry a type, and `document` is the generic one it provides for a
    work whose kind is unknown.
    """
    return CSL_TYPES.get(value, "document")


def work_csl_json(w: dict) -> dict:
    """CSL-JSON item for a work, omitting any other field missing from the source.

    ``type`` is never omitted -- CSL requires every item to carry one -- so it
    always goes through ``csl_type()``, which supplies the ``document``
    fallback for a work type this site doesn't recognise.
    """
    item: dict = {"id": w["id"], "type": csl_type(w.get("type"))}
    if w.get("title"):
        item["title"] = w["title"]
    authors = [{"literal": a["name"]} for a in w.get("authors") or [] if a.get("name")]
    if authors:
        item["author"] = authors
    issued = _csl_issued(w)
    if issued:
        item["issued"] = issued
    container_title = (w.get("source") or {}).get("name")
    if container_title:
        item["container-title"] = container_title
    doi = _csl_doi(w.get("doi"))
    if doi:
        item["DOI"] = doi
    return item


def ris_value(value) -> str:
    """Keep a value on one RIS line, so it cannot introduce another tag."""
    return str(value).replace("\r\n", " ").replace("\r", " ").replace("\n", " ")


def render_ris(w: dict) -> str:
    """Serialize the bibliographic fields exported for one work as one RIS record."""
    fields = [("TY", RIS_TYPES.get(w.get("type"), "GEN"))]

    def add(tag: str, value) -> None:
        if value is not None:
            value = ris_value(value)
            if value:
                fields.append((tag, value))

    add("TI", w.get("title"))
    for author in w.get("authors") or []:
        add("AU", author.get("name"))
    add("PY", w.get("date") or w.get("year"))
    add("T2", (w.get("source") or {}).get("name"))
    add("DO", w.get("doi"))
    fields.append(("ER", ""))
    return "".join(f"{tag}  - {value}\n" for tag, value in fields)


def render_csl_json(w: dict) -> str:
    """The CSL-JSON item for a work, serialized as the ``citation.csl.json`` artifact.

    ensure_ascii=False keeps non-Latin titles as literal UTF-8 rather than
    \\uXXXX escapes; sort_keys keeps two renders of the same work byte-identical.
    """
    return json.dumps(work_csl_json(w), ensure_ascii=False, indent=2, sort_keys=True) + "\n"



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


def load_optional(name: str, default):
    path = DATA / name
    return json.loads(path.read_text()) if path.exists() else default


def search_index(works: list, authors: list, institutions: list, topics: list) -> list[dict]:
    """Project browse indexes into the small, stable global search contract."""
    return [
        {
            "kind": kind,
            "id": row["id"],
            "label": row[label],
            **({"state": row[state]} if state else {}),
        }
        for kind, label, state, rows in (
            ("work", "title", "quality", works),
            ("author", "name", "band", authors),
            ("institution", "name", None, institutions),
            ("topic", "name", None, topics),
        )
        for row in rows
    ]


def field_navigation(root: str, class_name: str = "field-nav") -> str:
    """Links for the directory and every normalized field in shared chrome."""
    links = [f'<a href="{root}fields/">Fields</a>']
    links.extend(
        f'<a href="{root}fields/{e(field["key"])}/">{e(field["name"])}</a>'
        for field in NAV_FIELDS
    )
    return f'<nav class="{class_name}" aria-label="Corpus fields">' + "".join(links) + "</nav>"


def corpus_label(corpus: dict) -> str:
    """Name a legacy single field or a multi-field corpus in shared copy."""
    definition = corpus["definition"]
    if definition.get("name"):
        return definition["name"]
    return "multiple fields"


def corpus_description(corpus: dict) -> str:
    definition = corpus["definition"]
    return definition.get("description") or "A corpus spanning multiple normalized fields."


# -- chrome ---------------------------------------------------------------

def page(*, title: str, description: str, body: str, path: str, extra_head: str = "",
         island: bool = False) -> str:
    canonical = canonical_url(path)
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
  <form class="global-search" role="search" data-global-search
        data-index="{root}data/search-index.json" data-root="{root}">
    <label class="sr-only" for="global-q">Search the corpus</label>
    <input type="search" id="global-q" placeholder="Search papers, authors, institutions, and topics"
           data-search-input aria-controls="global-results" autocomplete="off">
    <div class="search-results" id="global-results" role="region" aria-live="polite"
         aria-label="Global search results"></div>
  </form>
  <nav class="site-nav" aria-label="Site navigation">
    <a href="{root}works/">Papers</a>
    <a href="{root}authors/">Authors</a>
    <a href="{root}institutions/">Institutions</a>
    <a href="{root}topics/">Topics</a>
    <a href="{root}methodology/">Methodology</a>
  </nav>
  {field_navigation(root)}
</div></header>
<main class="wrap">
{body}
</main>
<script src="{root}assets/app.js" defer></script>
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
    out.write_text(content, encoding="utf-8")
    return len(content)


# -- graph ----------------------------------------------------------------

def label_boxes(
    g: dict, *, focus: str = ""
) -> list[tuple[str, str, tuple[float, float, float, float]]]:
    """Greedy label placement, largest node first, clamped to the viewBox.

    Returns `(node_id, short_label, box)` for every label kept. `svg_graph` is
    the only caller; pulled out as a public helper so the placement geometry
    can be tested without re-parsing SVG.
    """
    nodes_data = [
        {
            **n,
            "label": n.get("label") or n.get("name") or n["id"],
            "kind": n.get("kind") or ("focus" if n["id"] == focus else "coauthor"),
        }
        for n in (g.get("nodes") or [])
    ]
    maxc = max((n.get("cited") or n.get("works") or 1) for n in nodes_data) or 1

    box_h = 12
    inset = 4
    # A graph shorter than a box plus both insets can't fit a clamp with room
    # to spare; the lower bound wins so the box never inverts.
    top_lo = inset
    top_hi = max(top_lo, g["height"] - inset - box_h)

    placed: list[tuple[float, float, float, float]] = []
    ordered = sorted(
        nodes_data,
        key=lambda n: (n["kind"] != "focus", -(n.get("cited") or n.get("works") or 0)),
    )
    out: list[tuple[str, str, tuple[float, float, float, float]]] = []
    for n in ordered:
        label = n["label"]
        short = label if len(label) <= 30 else label[:29] + "…"
        scale = (n.get("cited") or n.get("works") or 1) / maxc
        r = 11 if n["kind"] == "focus" else 5 + 11 * math.sqrt(max(scale, 0.0))
        half = len(short) * 2.7
        for dy in (-r - 5, r + 11):
            top = min(max(n["y"] + dy - 9, top_lo), top_hi)
            box = (n["x"] - half, top, n["x"] + half, top + box_h)
            if not any(
                box[0] < q[2] and q[0] < box[2] and box[1] < q[3] and q[1] < box[3]
                for q in placed
            ):
                placed.append(box)
                out.append((n["id"], short, box))
                break
    return out


def svg_graph(g: dict, href: dict[str, str], caption: str,
              *, kind: str = "citation", focus: str = "",
              href_prefix: str = "../") -> str:
    """Inline SVG from coordinates solved at export time.

    No <script>: the graph is in the markup, so it renders with JavaScript off,
    it is in the page a crawler sees, and it cannot shift between readers.
    """
    if not g or len(g.get("nodes") or []) < 2:
        return ""
    # Exported institution nodes use `name` and omit the work-graph-only
    # `kind`/`cited` fields. Normalize those optional fields here so the static
    # renderer stays compatible with both graph payload shapes.
    nodes_data = [
        {
            **n,
            "label": n.get("label") or n.get("name") or n["id"],
            "kind": n.get("kind") or ("focus" if n["id"] == focus else "coauthor"),
        }
        for n in (g.get("nodes") or [])
    ]
    pos = {n["id"]: (n["x"], n["y"]) for n in nodes_data}
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
    labels: dict[str, tuple[float, str]] = {
        node_id: (box[1] + 9, short)
        for node_id, short, box in label_boxes(g, focus=focus)
    }

    nodes = []
    for n in nodes_data:
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
    payload = dict(g, nodes=nodes_data, kind=kind, focus=focus, href_prefix=href_prefix)
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


def cohort_summary(authors: list[dict], works: list[dict]) -> str:
    """Show every uncertainty band, counted from the complete page lists."""
    groups = (
        ("identity", "Identity confidence", authors, "confidence", ("high", "medium", "low")),
        ("quality", "Record quality", works, "quality", ("complete", "partial", "suspect")),
    )
    summary = []
    for cohort, title, members, field, bands in groups:
        counts = {band: sum(member.get(field) == band for member in members) for band in bands}
        rows = "".join(
            f'<li data-band="{band}"><span class="badge {band}">{band}</span>'
            f'<b>{num(counts[band])}</b></li>'
            for band in bands
        )
        summary.append(
            f'<section class="cohort-group" data-cohort="{cohort}"><p>{title}</p>'
            f'<ul class="cohort-bands">{rows}</ul></section>'
        )
    return f'<div class="cohort-summary" aria-label="Cohort summary">{"".join(summary)}</div>'


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


def valid_source_url(url) -> bool:
    """True only for an absolute http(s) URL a reader could paste and follow.

    Whitespace and the other control characters are rejected as well as the
    obvious failures, and not for tidiness: a browser strips tabs and newlines
    out of an href before resolving it and escapes what is left, so a URL
    carrying one is not the URL the page displays.

    The authority has to resolve to a host and not merely be non-empty --
    `https://@/works/W1` and `https://:8443/works/W1` both have one, and neither
    names anything to fetch from.
    """
    if not isinstance(url, str) or not url:
        return False
    if any(c.isspace() or not c.isprintable() for c in url):
        return False
    try:
        parsed = urlsplit(url)
        _port = parsed.port  # raises on a malformed port
    except ValueError:  # an unparseable authority, e.g. a truncated IPv6 literal
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


def payload_source_link(sha: str, url) -> str:
    """The payload hash, linked to the URL those bytes were fetched from.

    The hash is the anchor text and not the URL itself because a harvested URL
    here is a 900-character OR-filter over 50 ids; the methodology page is where
    source URLs are read, and this is where they are followed.

    Escaping is the whole of the safety: `e` turns `"`, `<`, `>` and `&` into
    character references, so the href ends at the quote this renderer wrote
    rather than at one inside the data, and an HTML parser hands the stored URL
    back character for character. A URL that fails validation is not linked at
    all -- an anchor a reader cannot follow claims a check this site never made.
    """
    if not valid_source_url(url):
        return f'<span class="mono">sha256 {e(sha)}</span>'
    return f'<a class="mono" href="{e(url)}">sha256 {e(sha)}</a>'


def rejected_source_note(url) -> str:
    """Text noting a source URL that failed validation, beside the plain hash.

    Only shown when `payload_source_link` declined to link the hash: an absent
    or blank value says so plainly, and a present-but-invalid value is echoed
    as text so a bad manifest entry is still visible, never silently dropped.
    """
    if url is None or (isinstance(url, str) and not url.strip()):
        return '<span class="source faint">source URL not recorded</span>'
    return f'<span class="source faint">source {e(url)}</span>'


def provenance_html(raw, payloads: dict) -> str:
    """Show every source payload behind an aggregate, with its fetch date and source."""
    hashes = sorted(set(raw if isinstance(raw, list) else [raw] if raw else []))
    if not hashes:
        return '<p class="faint">No source payload hash was recorded.</p>'
    rows = []
    for sha in hashes:
        payload = payloads.get(sha) or {}
        url = payload.get("url")
        fetched = payload.get("fetched_at", "unknown")
        note = "" if valid_source_url(url) else f" {rejected_source_note(url)}"
        rows.append(
            f'<li>{payload_source_link(sha, url)} '
            f'<span class="faint">fetched {e(fetched)}</span>{note}</li>'
        )
    return '<ul class="evidence provenance-list">' + "".join(rows) + "</ul>"


def crossref_comparison_html(comparison: dict | None) -> str:
    """Show how this work's OpenAlex venue/type compare against Crossref, if we have one."""
    if not comparison:
        return ""
    rows = "".join(
        f'<li><span class="badge {e(status)}">{e(status)}</span> <span>{e(label)}</span></li>'
        for label, status in (
            ("venue", comparison["venue_status"]),
            ("work type", comparison["work_type_status"]),
        )
    )
    return f"""
  <div class="panel">
    <h2>Crossref comparison</h2>
    <p class="meta">How this work's OpenAlex venue and type compare against a Crossref assertion.</p>
    <ul class="evidence">{rows}</ul>
  </div>
"""


SOURCE_LABELS = {"openalex": "OpenAlex", "crossref": "Crossref", "europepmc": "Europe PMC"}


def record_comparison_html(comparison: dict | None, payloads: dict) -> str:
    """Every present source's title, venue and date, each labelled, with the
    verdict beside them. A field block may lack a `crossref` (or `europepmc`)
    entry for a work that only one of those sources covers; `openalex` is
    always present.

    The OpenAlex record above this panel is unchanged by anything here: a
    disagreement is shown, not resolved.
    """
    if not comparison:
        return ""
    sections = []
    for key, label in (("title", "Title"), ("venue", "Venue"), ("date", "Publication date")):
        field = comparison[key]
        status = field["status"]
        precision = field.get("precision")
        scope = f' <span class="faint">compared to the {e(precision)}</span>' if precision else ""
        rows = []
        for source in ("openalex", "crossref", "europepmc"):
            assertion = field.get(source)
            if assertion is None:
                continue
            value = e(assertion["value"]) if assertion["value"] else '<span class="faint">not asserted</span>'
            fetched = payloads.get(assertion["raw"], {}).get("fetched_at", "unknown")
            rows.append(
                f'<li><b>{e(SOURCE_LABELS.get(source, source))}</b>: {value} '
                f'<span class="mono faint">sha256 {e(assertion["raw"])} &middot; fetched {e(fetched)}</span></li>'
            )
        sections.append(
            f'<li><span class="badge {e(status)}">{e(status)}</span> <span>{label}</span>{scope}'
            f'<ul class="evidence">{"".join(rows)}</ul></li>'
        )
    role = comparison["role"]
    return f"""
  <div class="panel">
    <h2>Title and date across sources</h2>
    <p class="meta">{e(role[:1].upper() + role[1:])}. The record above stays as OpenAlex published it.</p>
    <ul class="evidence">{"".join(sections)}</ul>
  </div>
"""


def source_comparison_html(comparison: dict | None, payloads: dict) -> str:
    """Venue, work type, title and date, one row per source assertion, each with
    its own provenance. Title and date carry the four-way verdict from
    `quality.source_verdict`, so a Europe-PMC-only disagreement is shown as
    `europepmc_disagrees`, distinct from a Crossref-only `crossref_disagrees`.

    Additive only, like `record_comparison_html`: nothing here edits or merges
    the OpenAlex record above it. Omitted entirely when the export carries no
    `source_comparison` block, which is the case for every work page built
    from the committed `web/data` release until an operator re-runs the
    harvest, derive and export with t2's Crossref venue/type comparison.
    """
    if not comparison:
        return ""
    sections = []
    for key, label in (("venue", "Venue"), ("work_type", "Work type"), ("title", "Title"), ("date", "Publication date")):
        field = comparison.get(key)
        if field is None:
            continue
        status = field["status"]
        precision = field.get("precision")
        scope = f' <span class="faint">compared to the {e(precision)}</span>' if precision else ""
        rows = []
        for source_row in (field["openalex"], *field["crossref"], *field.get("europepmc", ())):
            value = e(source_row["value"]) if source_row["value"] else '<span class="faint">not asserted</span>'
            fetched = payloads.get(source_row["raw"], {}).get("fetched_at", "unknown")
            rows.append(
                f'<li><b>{e(source_row["source"])}</b>: {value} '
                f'<span class="mono faint">sha256 {e(source_row["raw"])} &middot; fetched {e(fetched)}</span></li>'
            )
        sections.append(
            f'<li><span class="badge {e(status)}">{e(status)}</span> <span>{label}</span>{scope}'
            f'<ul class="evidence">{"".join(rows)}</ul></li>'
        )
    role = comparison["role"]
    return f"""
  <div class="panel">
    <h2>Venue, work type, title and date across sources</h2>
    <p class="meta">{e(role)}</p>
    <ul class="evidence">{"".join(sections)}</ul>
  </div>
"""


def author_provenance(a: dict, work_raw: dict[str, object]) -> tuple[str | list[str], bool]:
    """Resolve an author's direct payload, or the payloads of its exported works."""
    if a.get("raw"):
        return a["raw"], False
    hashes = set()
    for linked_work in a.get("works", []):
        raw = work_raw.get(linked_work.get("id"))
        hashes.update(raw if isinstance(raw, list) else [raw] if raw else [])
    return sorted(hashes), True


def entity_link(kind: str, item: dict, available: set[str], *, prefix: str = "../../") -> str:
    """Link an entity only when its detail page exists in this data release."""
    ident = item.get("id")
    label = item.get("name") or item.get("display_name") or ident or ""
    if ident in available:
        return f'<a href="{prefix}{kind}/{e(ident)}/">{e(label)}</a>'
    return e(label)


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


CITATION_SOURCE_NAMES = {
    "openalex": "OpenAlex",
    "opencitations": "OpenCitations",
    "europepmc": "Europe PMC",
    "crossref": "Crossref",
    "arxiv": "arXiv",
    "semanticscholar": "Semantic Scholar",
}

CITATION_SOURCE_ONLY_LABELS = {
    "openalex": "OpenAlex only",
    "opencitations": "OpenCitations only — unconfirmed by OpenAlex",
    "europepmc": "Europe PMC only",
    "crossref": "Crossref only — unconfirmed by OpenAlex",
    "arxiv": "arXiv only — unconfirmed by OpenAlex",
    "semanticscholar": "Semantic Scholar only — unconfirmed by OpenAlex",
}


def citation_edge_status(edge: dict) -> tuple[str, str]:
    """Return a stable machine name and reader-facing source assessment."""
    raw_sources = edge.get("sources") or []
    sources = {raw_sources} if isinstance(raw_sources, str) else set(raw_sources)
    present = [s for s in CITATION_SOURCE_NAMES if s in sources]
    if len(present) >= 2:
        names = [CITATION_SOURCE_NAMES[s] for s in present]
        label = ", ".join(names[:-1]) + " and " + names[-1]
        return "corroborated", f"Corroborated — {label}"
    if len(present) == 1:
        source = present[0]
        return f"{source}-only", CITATION_SOURCE_ONLY_LABELS[source]
    return "legacy", "Legacy edge — source detail unavailable"


def citation_edge_evidence(g: dict) -> str:
    """Render one durable evidence row for every directed work-graph edge."""
    edges = g.get("edges") or []
    labels = {
        node["id"]: node.get("label") or node.get("name") or node["id"]
        for node in (g.get("nodes") or [])
    }
    rows = []
    for edge in edges:
        citing, cited = edge["s"], edge["t"]
        status, status_label = citation_edge_status(edge)
        rows.append(
            f'<li data-citing="{e(citing)}" data-cited="{e(cited)}" '
            f'data-evidence-status="{status}">'
            f'<span class="edge-pair"><a href="../{e(citing)}/">{e(labels.get(citing, citing))}</a>'
            f'<span class="edge-direction" aria-label="cites">&rarr;</span>'
            f'<a href="../{e(cited)}/">{e(labels.get(cited, cited))}</a></span>'
            f'<span class="edge-status {status}">{status_label}</span></li>'
        )
    contents = (
        f'<ul class="edge-evidence-list">{"".join(rows)}</ul>'
        if rows else '<p class="faint">No citation edges in this exported neighbourhood.</p>'
    )
    return f"""<section class="edge-evidence" aria-labelledby="citation-edge-evidence">
<h2 id="citation-edge-evidence">Citation edge evidence</h2>
<p class="meta">Each row is directed from the citing work to the cited work. Source status remains readable without the interactive graph.</p>
{contents}
</section>"""


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


def stacked_bar(segments: list[tuple[str, int, str]], *, label: str, width: int = 470,
                links: dict[str, str] | None = None) -> str:
    """A 100% bar for a three-way split, with every segment directly labelled.

    Status colours, not series colours -- and each one carries its own word, so
    the colour never has to be read on its own.
    """
    total = sum(v for _, v, _ in segments) or 1
    links = links or {}
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
        count = (
            f'<a class="chart-cohort-link" href="{e(links[name])}"><b>{num(value)}</b></a>'
            if name in links else f'<b>{num(value)}</b>'
        )
        legend.append(
            f'<span><i class="legend-{tone}"></i>{e(name)} {count} '
            f'<span class="faint">{value / total:.0%}</span></span>'
        )
        x += w + gap
    return f'''<figure class="chart">
<p class="chart-title">{e(label)}</p>
<svg viewBox="0 0 {width} {height}" role="img" aria-label="{e(label)}">{"".join(rects)}</svg>
<div class="chart-legend">{"".join(legend)}</div>
</figure>'''



def render_work(w: dict, authors: dict, titles: dict, payloads: dict,
                quality_notes: dict, topic_ids: set[str] | None = None) -> str:
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

    topic_ids = topic_ids or set()
    rows = "".join(
        f'<tr><td>{entity_link("t", t, topic_ids)}</td>'
        f'<td class="faint">{e(t["field"] or "")}</td></tr>'
        for t in w["topics"]
    )
    field_names = {field["key"]: field["name"] for field in NAV_FIELDS}
    field_links = "".join(
        f'<li><a href="../../fields/{e(key)}/">{e(field_names[key])}</a></li>'
        for key in w.get("fields", [])
        if key in field_names
    )
    fields = (
        f'<section class="field-memberships" aria-labelledby="field-memberships-heading">'
        f'<h2 id="field-memberships-heading">Fields</h2><ul>{field_links}</ul></section>'
        if field_links else ""
    )
    links = [
        '<a href="citation.bib" download>Download BibTeX</a>',
        '<a href="citation.ris" download>Download RIS</a>',
        '<a href="citation.csl.json" download>Download CSL-JSON</a>',
    ]
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
  {citation_edge_evidence(w["graph"])}
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
  {fields}
  <div class="panel">
    <h2>Is this record sound?</h2>
    <p><span class="badge {q["band"]}">{q["band"]}</span></p>
    <p>{e(q["sentence"])}</p>
    {evidence_html(q["evidence"], quality_notes)}
  </div>
  <div class="panel">
    <h2>Provenance</h2>
    <p class="meta">This work record resolves to the stored source payload below.</p>
    {provenance_html(w.get("raw"), payloads)}
  </div>
  {crossref_comparison_html(w.get("crossref_comparison"))}
  {record_comparison_html(w.get("record_comparison"), payloads)}
  {source_comparison_html(w.get("source_comparison"), payloads)}
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
        extra_head=work_head_metadata(w, canonical_url(f"w/{wid}/")),
        island=True,
    )


def render_author(a: dict, notes: dict, bands: dict, payloads: dict,
                  institution_ids: set[str] | None = None,
                  work_raw: dict[str, object] | None = None) -> str:
    band = a["confidence"]["band"]
    works_rows = "".join(
        f'<tr><td><a href="../../w/{e(w["id"])}/">{e(w["title"])}</a></td>'
        f'<td class="faint">{e(w["position"] or "")}</td>'
        f'<td class="num">{e(w["year"] or "")}</td>'
        f'<td class="num">{num(w["cited"])}</td></tr>'
        for w in a["works"]
    )
    institution_ids = institution_ids or set()
    insts = ", ".join(
        entity_link("i", i, institution_ids)
        + (f' <span class="faint">({i["first_year"]}–{i["last_year"]})</span>'
           if i.get("first_year") else "")
        for i in a["institutions"]
    ) or '<span class="faint">No institution on the works in this corpus.</span>'

    href = {n["id"]: f"../{n['id']}/" for n in a["graph"]["nodes"]}
    href[a["id"]] = ""
    collaborators = [
        n for n in a["graph"]["nodes"]
        if n["kind"] == "coauthor" and n["id"] != a["id"]
    ]
    collaborator_list = (
        '<ol class="collaborator-list">'
        + "".join(
            f'<li><a href="../{e(n["id"])}/">{e(n["label"])}</a></li>'
            for n in collaborators
        )
        + "</ol>"
        if collaborators else ""
    )
    caption = (
        f'{a["graph"]["shown"]} of {a["graph"]["available"]} collaborators, ranked by '
        f'collaboration weight rather than by shared-paper count. Dashed lines are '
        f'collaborations between the collaborators. See '
        f'<a href="../../methodology/">how the weight is computed</a>.'
    )
    author_raw, used_work_fallback = author_provenance(a, work_raw or {})
    provenance_note = (
        "No direct source payload hash was recorded for this author. Provenance "
        "therefore resolves through the stored payloads for linked exported works."
        if used_work_fallback else
        "This author record resolves to the stored source payload below."
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
  {collaborator_list}
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
  <div class="panel">
    <h2>Provenance</h2>
    <p class="meta">{provenance_note}</p>
    {provenance_html(author_raw, payloads)}
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
        extra_head=author_head_metadata(a, canonical_url(f"a/{a['id']}/")),
        island=True,
    )


def render_institution(i: dict, payloads: dict, author_ids: set[str],
                       work_ids: set[str]) -> str:
    iid = i["id"]
    author_members = i.get("authors", [])
    work_members = i.get("works", [])
    authors = "".join(
        f'<tr><td>{entity_link("a", a, author_ids)}</td>'
        f'<td class="num">{num(a.get("works") or 0)}</td>'
        f'<td class="num">{num(a.get("cited_by_count") or 0)}</td>'
        f'<td>{badge(a.get("confidence"))}</td></tr>'
        for a in author_members
    )
    works = "".join(
        f'<tr><td>{entity_link("w", w, work_ids)}</td>'
        f'<td class="num">{e(w.get("year") or "")}</td>'
        f'<td class="num">{num(w.get("cited") or 0)}</td>'
        f'<td>{badge(w.get("quality"))}</td></tr>'
        for w in work_members
    )
    graph = i.get("graph") or {}
    href = {n["id"]: f"../../a/{n['id']}/" for n in graph.get("nodes", []) if n["id"] in author_ids}
    caption = (
        f'{graph.get("shown", 0)} of {graph.get("available", 0)} authors shown in the '
        "precomputed collaboration graph. Coordinates come from the export."
    )
    metadata = i.get("metadata") or {}
    openalex_link = (
        f'<a href="{e(i["openalex_url"])}">OpenAlex record</a>'
        if i.get("openalex_url") else ""
    )
    empty = not author_members and not work_members
    empty_note = (
        '<p class="withheld">This institution is present only as a last-known '
        'institution in author payloads. No work in this corpus carries an '
        'affiliation to it, so its author list, work list, and collaboration graph '
        'are intentionally empty.</p>'
        if empty else ""
    )
    body = f"""
<h1>{e(i["name"])}</h1>
<p class="meta">{num(len(author_members))} author(s) &middot;
   {num(len(work_members))} work(s)
   {" &middot; " + e(metadata["country_code"]) if metadata.get("country_code") else ""}
   {" &middot; " + e(metadata["type"]) if metadata.get("type") else ""}</p>
{empty_note}
{cohort_summary(author_members, work_members)}
<div class="grid two">
<div>
  {svg_graph(graph, href, caption, kind="collaboration", focus="", href_prefix="../../")}
  <div class="legend"><span><i style="background:var(--ref)"></i>author</span>
    <span>line weight = collaboration weight</span></div>
  <h2 style="margin-top:26px">Authors</h2>
  <div class="scroll"><table>
    <thead><tr><th>Author</th><th class="num">Works</th><th class="num">Cited</th><th>Identity</th></tr></thead>
    <tbody>{authors or '<tr><td class="faint" colspan="4">None affiliated in this corpus.</td></tr>'}</tbody>
  </table></div>
</div>
<div>
  <div class="panel"><h2>Works</h2>
  <div class="scroll"><table><thead><tr><th>Title</th><th class="num">Year</th><th class="num">Cited</th><th>Quality</th></tr></thead>
    <tbody>{works or '<tr><td class="faint" colspan="4">None affiliated in this corpus.</td></tr>'}</tbody>
  </table></div></div>
  <div class="panel"><h2>Details</h2>
    <p>{openalex_link}</p>
    <p class="meta">ROR {e(metadata.get("ror") or "not recorded")}</p>
  </div>
  <div class="panel"><h2>Provenance</h2>
    <p class="meta">This aggregate combines the stored institution, author, and work records behind the lists and graph.</p>
    {provenance_html(i.get("raw"), payloads)}
  </div>
</div>
</div>
"""
    return page(
        title=f'{i["name"]} — {SITE_NAME}',
        description=f'{i["name"]}: affiliated authors, works, and a precomputed collaboration graph.',
        body=body,
        path=f"i/{iid}/",
        extra_head=institution_head_metadata(i, canonical_url(f"i/{iid}/")),
    )


def render_topic(t: dict, payloads: dict, work_ids: set[str], author_ids: set[str]) -> str:
    work_members = t.get("works", [])
    author_members = t.get("authors", [])
    works = "".join(
        f'<tr><td>{entity_link("w", w, work_ids)}</td>'
        f'<td class="num">{e(w.get("year") or "")}</td>'
        f'<td class="num">{num(w.get("cited") or 0)}</td>'
        f'<td>{badge(w.get("quality"))}</td></tr>'
        for w in work_members
    )
    authors = "".join(
        f'<tr><td>{entity_link("a", a, author_ids)}</td>'
        f'<td class="num">{num(a.get("participation") or 0)}</td>'
        f'<td class="num">{num(a.get("cited_by_count") or 0)}</td>'
        f'<td>{badge(a.get("confidence"))}</td></tr>'
        for a in author_members
    )
    metadata = t.get("metadata") or {}
    openalex_link = (
        f'<a href="{e(t["openalex_url"])}">OpenAlex record</a>'
        if t.get("openalex_url") else ""
    )
    body = f"""
<h1>{e(t["name"])}</h1>
<p class="meta">{num(len(work_members))} work(s) &middot;
   {num(len(author_members))} participating author(s)
   {" &middot; " + e(metadata["field"]) if metadata.get("field") else ""}
   {" &middot; " + e(metadata["domain"]) if metadata.get("domain") else ""}</p>
{cohort_summary(author_members, work_members)}
<div class="grid two">
<div>
  <h2>Citation-ranked works</h2>
  <div class="scroll"><table>
    <thead><tr><th>Title</th><th class="num">Year</th><th class="num">Cited</th><th>Quality</th></tr></thead>
    <tbody>{works or '<tr><td class="faint" colspan="4">No works in this corpus.</td></tr>'}</tbody>
  </table></div>
</div>
<div>
  <div class="panel"><h2>Participating authors</h2>
  <div class="scroll"><table><thead><tr><th>Author</th><th class="num">Works</th><th class="num">Cited</th><th>Identity</th></tr></thead>
    <tbody>{authors or '<tr><td class="faint" colspan="4">No authors in this corpus.</td></tr>'}</tbody>
  </table></div></div>
  <div class="panel"><h2>Details</h2>
    <p>{openalex_link}</p>
  </div>
  <div class="panel"><h2>Provenance</h2>
    <p class="meta">This aggregate combines the stored topic, work, and author records behind these rankings.</p>
    {provenance_html(t.get("raw"), payloads)}
  </div>
</div>
</div>
"""
    return page(
        title=f'{t["name"]} — {SITE_NAME}',
        description=f'{t["name"]}: citation-ranked works and participating authors.',
        body=body,
        path=f"t/{t['id']}/",
        extra_head=topic_head_metadata(t, canonical_url(f"t/{t['id']}/")),
    )


def render_home(corpus: dict, works: list, authors: list,
                fields: list[dict] | None = None,
                field_works: dict[str, list] | None = None) -> str:
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
    # One summary per normalized field, only once there is more than one to tell
    # apart. A single-field corpus is the shipped release: it must keep the
    # aggregate page byte for byte, so this stays "" and is interpolated with no
    # surrounding whitespace of its own.
    field_sections = ""
    if fields is not None and len(fields) > 1:
        members_by_key = field_works or {}
        panels = []
        for field in fields:
            members = members_by_key.get(field["key"], [])
            count = field.get("works")
            if count is None:
                count = len(members)
            rows = "".join(
                f'<tr><td><a href="w/{e(member["id"])}/">{e(member["title"])}</a></td>'
                f'<td class="num">{num(member["cited"])}</td></tr>'
                for member in members[:5]
            )
            description = field.get("description")
            blurb = f'\n  <p>{e(description)}</p>' if description else ""
            panels.append(f"""<div class="panel">
  <h2><a href="fields/{e(field["key"])}/">{e(field["name"])}</a></h2>
  <p class="meta">{num(count)} papers</p>{blurb}
  <div class="scroll"><table>
    <thead><tr><th>Paper</th><th class="num">Cited</th></tr></thead>
    <tbody>{rows or '<tr><td class="faint" colspan="2">No papers exported for this field.</td></tr>'}</tbody>
  </table></div>
</div>""")
        field_sections = ('\n<div class="grid two-even">\n'
                          + "\n".join(panels) + "\n</div>")
    body = f"""
<h1>{TAGLINE}</h1>
<p class="lede">{e(corpus_description(corpus))} Every page is precomputed and
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
     <b>{e(corpus_label(corpus))}</b> subfield, every author on them, and every
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
</div>{field_sections}
<div class="grid two-even">
{bar_chart(sorted(year_counts.items()), label=f"Works by publication year ({len(year_counts)} years)")}
</div>
<div class="grid two-even">
{stacked_bar([("high", ident["high"], "good"), ("medium", ident["medium"], "warning"),
              ("low", ident["low"], "critical")],
             label="Is each author record one person?",
             links={"low": "authors/low-confidence/"})}
{stacked_bar([("complete", q["complete"], "good"), ("partial", q["partial"], "warning"),
              ("suspect", q["suspect"], "critical")],
             label="Does each paper record agree with itself?",
             links={"partial": "works/partial/", "suspect": "works/suspect/"})}
</div>

<h2>Most cited</h2>
<div class="scroll"><table>
  <thead><tr><th>Paper</th><th class="num">Year</th><th class="num">Cited</th><th class="num">In corpus</th></tr></thead>
  <tbody>{top}</tbody>
</table></div>
<p class="meta"><a href="works/">All {num(c["works"])} papers</a> &middot;
   <a href="fields/">Browse fields</a> &middot;
   <a href="authors/">All {num(c["authors"])} authors</a> &middot;
   <a href="institutions/">Browse institutions</a> &middot;
   <a href="topics/">Browse topics</a></p>
"""
    return page(
        title=f"{SITE_NAME} — {TAGLINE}",
        description=TAGLINE,
        body=body,
        path="",
        extra_head=home_head_metadata(canonical_url("")),
    )


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
    elif kind == "authors":
        head = '<tr><th>Author</th><th>Identity</th><th class="num">Works</th><th class="num">Collaborators</th><th class="num">Cited</th></tr>'
        body_rows = "".join(
            f'<tr><td><a href="../a/{e(r["id"])}/">{e(r["name"])}</a></td>'
            f'<td><span class="badge {r["band"]}">{r["band"]}</span></td>'
            f'<td class="num">{num(r["works"])}</td><td class="num">{num(r["coauthors"])}</td>'
            f'<td class="num">{num(r["cited"])}</td></tr>'
            for r in rows[:400]
        )
        title, index = "Authors", "authors-index.json"
    elif kind == "institutions":
        head = '<tr><th>Institution</th><th class="num">Authors</th><th class="num">Works</th><th class="num">Graph</th></tr>'
        body_rows = "".join(
            f'<tr><td><a href="../i/{e(r["id"])}/">{e(r["name"])}</a></td>'
            f'<td class="num">{num(r.get("authors") or 0)}</td>'
            f'<td class="num">{num(r.get("works") or 0)}</td>'
            f'<td class="num">{num(r.get("graph") or 0)}</td></tr>'
            for r in rows[:400]
        )
        title, index = "Institutions", "institutions-index.json"
    else:
        head = '<tr><th>Topic</th><th class="num">Works</th><th class="num">Authors</th></tr>'
        body_rows = "".join(
            f'<tr><td><a href="../t/{e(r["id"])}/">{e(r["name"])}</a></td>'
            f'<td class="num">{num(r.get("works") or 0)}</td>'
            f'<td class="num">{num(r.get("authors") or 0)}</td></tr>'
            for r in rows[:400]
        )
        title, index = "Topics", "topics-index.json"

    body = f"""
<h1>{title}</h1>
<p class="lede">{num(len(rows))} in this corpus. The table shows the first 400; search the
   whole set below.</p>
{field_navigation("../", "field-browse-nav") if kind == "works" else ""}
<label class="sr-only" for="collection-q">Search {title.lower()}</label>
<input type="search" id="collection-q" placeholder="Search all {num(len(rows))} {title.lower()}&hellip;"
       data-collection-search data-index="../data/{index}" data-kind="{kind}"
       aria-controls="collection-results" autocomplete="off">
<div class="hits" id="collection-results" role="status" aria-live="polite"></div>
<div class="scroll" id="collection-table"><table><thead>{head}</thead><tbody>{body_rows}</tbody></table></div>
"""
    return page(
        title=f"{title} — {SITE_NAME}",
        description=f"All {num(len(rows))} {title.lower()} in the {corpus_label(corpus)} corpus.",
        body=body,
        path=f"{kind}/",
        extra_head=breadcrumb_json_ld([("Home", ""), (title, f"{kind}/")]),
    )


def render_fields(fields: list[dict]) -> str:
    """Render the static directory of normalized corpus fields."""
    rows = "".join(
        f'<li><a href="{e(field["key"])}/">{e(field["name"])}</a>'
        f'<span>{num(field["works"])} papers</span>'
        + (f'<p>{e(field["description"])}</p>' if field.get("description") else "")
        + "</li>"
        for field in fields
    )
    body = f"""
<h1>Fields</h1>
<p class="lede">Browse every normalized field in this corpus. A paper can appear in more than one
   field; its detail page remains one canonical paper page.</p>
<ul class="field-directory">{rows}</ul>
"""
    return page(
        title=f"Fields — {SITE_NAME}",
        description="Every normalized field in this corpus and its complete paper list.",
        body=body,
        path="fields/",
        extra_head=breadcrumb_json_ld([("Home", ""), ("Fields", "fields/")]),
    )


def render_field(field: dict, works: list, corpus: dict) -> str:
    """Render every exported member of one field, in global works-index order."""
    rows = "".join(
        f'<tr><td><a href="../../w/{e(work["id"])}/">{e(work["title"])}</a>'
        f'<br><span class="meta faint">{e(", ".join(work["authors"]))}</span></td>'
        f'<td>{badge(work.get("quality"), hide="complete")}</td>'
        f'<td class="num">{e(work["year"] or "")}</td>'
        f'<td class="num">{num(work["cited"])}</td>'
        f'<td class="num">{num(work["in_corpus_cited"])}</td></tr>'
        for work in works
    )
    description = field.get("description") or (
        f'Every paper in the {field["name"]} field of this corpus.'
    )
    body = f"""
<h1>{e(field["name"])}</h1>
<p class="lede">{e(description)} {num(len(works))} papers, shown in the corpus-wide paper order.</p>
<div class="scroll"><table>
  <thead><tr><th>Paper</th><th>Record</th><th class="num">Year</th><th class="num">Cited</th><th class="num">In corpus</th></tr></thead>
  <tbody>{rows}</tbody>
</table></div>
"""
    return page(
        title=f'{field["name"]} papers — {SITE_NAME}',
        description=description,
        body=body,
        path=f'fields/{field["key"]}/',
        extra_head=breadcrumb_json_ld([
            ("Home", ""), ("Fields", "fields/"), (field["name"], f'fields/{field["key"]}/'),
        ]),
    )


def render_cohort(kind: str, band: str, index_rows: list) -> str:
    """Render an uncapped uncertainty cohort in its exported index order."""
    if kind == "authors":
        rows = [row for row in index_rows if row["band"] == band]
        title = "Low-confidence authors"
        description = "Author records whose identity confidence is low."
        head = ('<tr><th>Author</th><th>Identity</th><th class="num">Works</th>'
                '<th class="num">Collaborators</th><th class="num">Cited</th></tr>')
        body_rows = "".join(
            f'<tr><td><a href="../../a/{e(row["id"])}/">{e(row["name"])}</a></td>'
            f'<td><span class="badge {row["band"]}">{row["band"]}</span></td>'
            f'<td class="num">{num(row["works"])}</td><td class="num">{num(row["coauthors"])}</td>'
            f'<td class="num">{num(row["cited"])}</td></tr>'
            for row in rows
        )
        path = "authors/low-confidence/"
        noun = "author records"
    else:
        rows = [row for row in index_rows if row["quality"] == band]
        title = f"{band.capitalize()} paper records"
        description = f"Paper records whose stored quality assessment is {band}."
        head = ('<tr><th>Paper</th><th>Record</th><th class="num">Year</th>'
                '<th class="num">Cited</th><th class="num">In corpus</th></tr>')
        body_rows = "".join(
            f'<tr><td><a href="../../w/{e(row["id"])}/">{e(row["title"])}</a>'
            f'<br><span class="meta faint">{e(", ".join(row["authors"]))}</span></td>'
            f'<td>{badge(row["quality"], hide="complete")}</td>'
            f'<td class="num">{e(row["year"] or "")}</td><td class="num">{num(row["cited"])}</td>'
            f'<td class="num">{num(row["in_corpus_cited"])}</td></tr>'
            for row in rows
        )
        path = f"works/{band}/"
        noun = "paper records"

    body = f"""
<h1>{title}</h1>
<p class="lede">{num(len(rows))} {band} {noun} in this corpus. Every matching record is shown below.</p>
<div class="scroll"><table><thead>{head}</thead><tbody>{body_rows}</tbody></table></div>
"""
    return page(
        title=f"{title} — {SITE_NAME}",
        description=f"{description} The complete cohort is shown in exported index order.",
        body=body,
        path=path,
    )


def render_methodology(corpus: dict) -> str:
    abstracts = corpus["abstracts"]
    declared_sources = corpus.get("citation_sources", corpus["sources"])
    if isinstance(declared_sources, dict):
        declared_sources = declared_sources.values()
    src_rows = "".join(
        f'<tr><td>{e(s["name"])}</td>'
        f'<td><a href="{e(s["url"])}">{e(s["url"])}</a></td><td>{e(s["license"])}</td>'
        f'<td>{e(s["role"])}</td></tr>'
        for s in declared_sources
    )
    coverage = corpus.get("citation_edge_coverage")
    coverage_table = ""
    if coverage:
        total = coverage["total"]
        corroborated_total = sum(
            count for n, count in coverage["by_index_count"].items() if int(n) >= 2
        )
        coverage_rows = "".join(
            f'<tr><td>Asserted by {e(n)} index(es)</td><td class="num">{num(count)}</td>'
            f'<td class="num">{count / total:.0%}</td></tr>'
            for n, count in coverage["by_index_count"].items()
        )
        coverage_rows += "".join(
            f'<tr><td>{e(CITATION_SOURCE_NAMES.get(source, source))}</td>'
            f'<td class="num">{num(count)}</td>'
            f'<td class="num">{count / total:.0%}</td></tr>'
            for source, count in coverage["single_index"].items()
        )
        coverage_table = f"""<div class="scroll"><table>
  <thead><tr><th>Bucket</th><th class="num">Edges</th><th class="num">Share</th></tr></thead>
  <tbody>{coverage_rows}</tbody>
</table></div>
<p class="meta">Currently {num(corroborated_total)} of {num(total)} citation edges are corroborated.</p>
"""

    body = f"""
<h1>Methodology</h1>
<p class="lede">What is in this corpus, where every figure came from, and the three
   things this site refuses to do.</p>

<div class="panel">
<h2>Sources</h2>
<div class="scroll"><table>
  <thead><tr><th>Source</th><th>URL</th><th>Licence</th><th>Used for</th></tr></thead>
  <tbody>{src_rows}</tbody>
</table></div>
<p class="meta">Nothing here is scraped from a publisher's website. Every record comes
   from an open API or bulk dump under a licence that permits reuse, and each page
   names the stored payload it was rendered from.</p>
</div>

<div class="panel">
<h2>How citation edges are corroborated</h2>
<p>We call a citation edge <b>corroborated</b> when two or more independent indexes
   independently assert the same directed DOI-resolved edge: the same citing work
   points to the same cited work. OpenAlex, OpenCitations, Europe PMC and Crossref's
   own asserted citations each count as one such index.</p>
<p>An edge asserted by only one index remains visible. Its work-page evidence
   identifies the single index, and an OpenCitations-only or Crossref-only edge is
   explicitly marked unconfirmed by OpenAlex.</p>
{coverage_table}</div>

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
    global NAV_FIELDS
    if not DATA.exists():
        print("no web/data: run `python3 export_json.py` first", file=sys.stderr)
        return 1
    corpus = load("corpus.json")
    works_index = load("works-index.json")
    authors_index = load("authors-index.json")
    institutions_index = load_optional("institutions-index.json", [])
    topics_index = load_optional("topics-index.json", [])
    payloads = load("payloads.json")
    notes = corpus["identity_notes"]
    bands = corpus["identity_bands"]
    quality_notes = corpus["quality_notes"]

    exported_fields = load_optional("fields-index.json", None)
    membership_presence = ["fields" in work for work in works_index]
    has_any_memberships = any(membership_presence)
    has_all_memberships = all(membership_presence)
    if exported_fields is None and not has_any_memberships:
        # Checked-in releases predating the membership export have only the
        # legacy top-level definition.  It is one field, and every indexed work
        # belongs to it; do not infer memberships from unrelated work metadata.
        normalized = corpus_contract.normalize(corpus["definition"])
        field_key, definition = next(iter(normalized.items()))
        fields_index = [{
            "key": field_key,
            "name": definition["name"],
            "description": definition.get("description"),
            "works": len(works_index),
        }]
        field_works = {field_key: works_index}
        legacy_fields = [field_key]
    elif exported_fields is None or not has_all_memberships:
        print("incomplete field export: need both fields-index.json and work fields arrays", file=sys.stderr)
        return 1
    else:
        fields_index = exported_fields
        field_works = {
            field["key"]: [
                work for work in works_index if field["key"] in work["fields"]
            ]
            for field in fields_index
        }
        legacy_fields = []
    NAV_FIELDS = fields_index

    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir(parents=True)
    shutil.copytree(ASSETS, SITE / "assets")

    n = 0
    total = 0
    titles = {w["id"]: w for w in works_index}
    author_names = {a["id"]: a["name"] for a in authors_index}
    work_ids = set(titles)
    author_ids = set(author_names)
    institution_payloads = {}
    institution_dir = DATA / "institutions"
    if institution_dir.exists():
        for shard in sorted(institution_dir.glob("*.json")):
            institution_payloads.update(json.loads(shard.read_text()))
    topic_payloads = {}
    topic_dir = DATA / "topics"
    if topic_dir.exists():
        for shard in sorted(topic_dir.glob("*.json")):
            topic_payloads.update(json.loads(shard.read_text()))
    institution_ids = set(institution_payloads)
    topic_ids = set(topic_payloads)
    work_raw = {}

    for shard in sorted((DATA / "works").glob("*.json")):
        for wid, w in json.loads(shard.read_text()).items():
            # A legacy shard predates the membership export and carries no
            # `fields` of its own, so its page would show no Fields section at
            # all.  The sole normalized field owns every work there; an
            # export-driven shard already has its own keys and keeps them.
            w.setdefault("fields", legacy_fields)
            work_raw[wid] = w.get("raw")
            total += write(
                f"w/{wid}/index.html",
                render_work(w, author_names, titles, payloads, quality_notes, topic_ids),
            )
            total += write(f"w/{wid}/citation.bib", work_bibtex(w))
            total += write(f"w/{wid}/citation.ris", render_ris(w))
            total += write(f"w/{wid}/citation.csl.json", render_csl_json(w))
            n += 1

    for shard in sorted((DATA / "authors").glob("*.json")):
        for aid, a in json.loads(shard.read_text()).items():
            total += write(
                f"a/{aid}/index.html",
                render_author(a, notes, bands, payloads, institution_ids, work_raw),
            )
            n += 1

    for iid, institution in institution_payloads.items():
        total += write(
            f"i/{iid}/index.html",
            render_institution(institution, payloads, author_ids, work_ids),
        )
        n += 1

    for tid, topic in topic_payloads.items():
        total += write(
            f"t/{tid}/index.html",
            render_topic(topic, payloads, work_ids, author_ids),
        )
        n += 1

    total += write("index.html", render_home(corpus, works_index, authors_index, fields_index, field_works))
    total += write("works/index.html", render_browse("works", works_index, corpus))
    total += write("fields/index.html", render_fields(fields_index))
    for field in fields_index:
        total += write(
            f"fields/{field['key']}/index.html",
            render_field(field, field_works[field["key"]], corpus),
        )
    total += write("authors/index.html", render_browse("authors", authors_index, corpus))
    total += write("authors/low-confidence/index.html", render_cohort("authors", "low", authors_index))
    total += write("works/partial/index.html", render_cohort("works", "partial", works_index))
    total += write("works/suspect/index.html", render_cohort("works", "suspect", works_index))
    total += write("institutions/index.html", render_browse("institutions", institutions_index, corpus))
    total += write("topics/index.html", render_browse("topics", topics_index, corpus))
    total += write("methodology/index.html", render_methodology(corpus))
    n += 10 + len(fields_index)

    # The browse pages fetch these at runtime for search; the rest of the corpus
    # data is already baked into the HTML and is not shipped.
    (SITE / "data").mkdir(exist_ok=True)
    total += write(
        "data/search-index.json",
        json.dumps(
            search_index(works_index, authors_index, institutions_index, topics_index),
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    for name in (
        "works-index.json", "authors-index.json",
        "institutions-index.json", "topics-index.json",
    ):
        source = DATA / name
        if source.exists():
            shutil.copy(source, SITE / "data" / name)
        elif name in ("institutions-index.json", "topics-index.json"):
            # Keep the legacy build's empty browse searches local and valid.
            (SITE / "data" / name).write_text("[]")

    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n")
    urls = "".join(
        f"<url><loc>{SITE_URL}/{p}</loc></url>"
        for p in ["", "works/", "works/partial/", "works/suspect/", "fields/", "authors/",
                  "authors/low-confidence/", "institutions/", "topics/", "methodology/"]
        + [f"fields/{field['key']}/" for field in fields_index]
        + [f"w/{w['id']}/" for w in works_index]
        + [f"a/{a['id']}/" for a in authors_index]
        + [f"i/{i['id']}/" for i in institutions_index]
        + [f"t/{t['id']}/" for t in topics_index]
    )
    write("sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')

    print(f"== rendered {n} pages ({total / 1e6:.1f} MB) to {_display(SITE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
