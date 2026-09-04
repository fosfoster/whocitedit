#!/usr/bin/env python3
"""Offline coverage for static institution/topic pages and their links."""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import export_json
import render
import test_entity_export


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def internal_links(site: Path):
    for page in site.rglob("*.html"):
        for href in re.findall(r'href="([^"#]+)"', page.read_text()):
            if href.startswith(("http", "mailto:", "//")):
                continue
            yield page, href


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (export_json.OUT, export_json.DB_PATH, export_json.ROOT, render.DATA,
             render.SITE, render.ASSETS)
    try:
        db_path, expected_payloads, _ = test_entity_export.build_corpus(tmp)
        export_json.OUT = tmp / "data"
        export_json.DB_PATH = db_path
        export_json.ROOT = Path(__file__).parent
        bad += check(export_json.main() == 0, "export fixture failed")

        render.DATA = tmp / "data"
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "synthetic render failed")
        site = tmp / "site"
        institution_index = json.loads((tmp / "data" / "institutions-index.json").read_text())
        topic_index = json.loads((tmp / "data" / "topics-index.json").read_text())
        sitemap = (site / "sitemap.xml").read_text()

        # Every exported index entry has a detail page and sitemap URL.
        for prefix, entries in (("i", institution_index), ("t", topic_index)):
            for entry in entries:
                ident = entry["id"]
                detail = site / prefix / ident / "index.html"
                bad += check(detail.exists(), f"missing {prefix}/{ident} detail page")
                bad += check(f"/{prefix}/{ident}/" in sitemap, f"{ident} missing from sitemap")

        # Both collections are real pages, are linked from navigation/home, and
        # search points only at indexes copied into the generated site.
        home = (site / "index.html").read_text()
        for route in ("institutions", "topics"):
            browse = site / route / "index.html"
            browse_html = browse.read_text()
            bad += check(browse.exists(), f"missing {route} browse page")
            bad += check(f'href="{route}/"' in home, f"home does not link {route}")
            bad += check(f'href="../{route}/"' in browse_html, f"{route} navigation is missing")
            bad += check(f'data-index="../data/{route}-index.json"' in browse_html,
                         f"{route} search is not local")
            bad += check((site / "data" / f"{route}-index.json").exists(),
                         f"{route} search index was not copied")
            bad += check(f"/{route}/" in sitemap, f"{route} browse missing from sitemap")

        work = (site / "w" / "W1" / "index.html").read_text()
        author = (site / "a" / "A01" / "index.html").read_text()
        institution = (site / "i" / "I-AFF" / "index.html").read_text()
        last_known = (site / "i" / "I-LAST" / "index.html").read_text()
        topic = (site / "t" / "T1" / "index.html").read_text()
        bad += check('href="../../t/T1/"' in work, "work topic row does not link to topic page")
        bad += check('href="../../i/I-AFF/"' in author, "author affiliation row does not link to institution page")
        bad += check('href="../../a/A01/"' in institution and 'href="../../w/W1/"' in institution,
                     "institution page lost author/work links")
        bad += check("This institution is present only as a last-known" in last_known,
                     "last-known-only institution lacks its empty-corpus explanation")
        bad += check('href="../../w/W1/"' in topic and 'href="../../a/A01/"' in topic,
                     "topic page lost work/author links")
        bad += check(topic.index("W1") < topic.index("W2") < topic.index("W3"),
                     "topic works are not citation-ranked")

        # The institution graph is the export's coordinates rendered as inline
        # SVG; no reader-side force simulation is allowed on this page.
        bad += check("<svg" in institution and 'x="' in institution and 'y="' in institution,
                     "institution page has no inline graph coordinates")
        bad += check("forceSimulation" not in institution and "simulation" not in institution.lower(),
                     "institution graph contains a reader-side simulation")

        # Every aggregate source hash and its fetched date must be visible.
        payloads = json.loads((tmp / "data" / "payloads.json").read_text())
        for ident, page in (("I-AFF", institution), ("T1", topic), ("I-LAST", last_known)):
            shard_dir = "institutions" if ident.startswith("I-") else "topics"
            payload = json.loads((tmp / "data" / shard_dir / f"{export_json.shard(ident)}.json").read_text())[ident]
            for sha in payload["raw"]:
                bad += check(sha in page and payloads[sha]["fetched_at"] in page,
                             f"{ident} provenance omits {sha} or its fetched date")
        bad += check(set(payloads) == expected_payloads, "fixture provenance changed unexpectedly")

        # Resolve every relative HTML link in the synthetic output.
        broken = []
        for page, href in internal_links(site):
            target = (page.parent / href).resolve()
            if target.is_dir():
                target = target / "index.html"
            if not target.exists():
                broken.append(f"{page.relative_to(site)} -> {href}")
        bad += check(not broken, f"broken internal links: {broken[:4]}")

        # A legacy release without the new indexes/shards remains renderable and
        # does not manufacture links to details it cannot emit.
        legacy = tmp / "legacy-data"
        shutil.copytree(tmp / "data", legacy)
        for name in ("institutions-index.json", "topics-index.json"):
            (legacy / name).unlink()
        for directory in (legacy / "institutions", legacy / "topics"):
            shutil.rmtree(directory)
        render.DATA = legacy
        render.SITE = tmp / "legacy-site"
        bad += check(render.main() == 0, "legacy render failed")
        legacy_html = "".join(p.read_text() for p in (tmp / "legacy-site").rglob("*.html"))
        bad += check("/i/" not in legacy_html and "/t/" not in legacy_html,
                     "legacy render emitted dangling entity links")
    finally:
        (export_json.OUT, export_json.DB_PATH, export_json.ROOT, render.DATA,
         render.SITE, render.ASSETS) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_entity_pages:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
