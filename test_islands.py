#!/usr/bin/env python3
"""The island contract: the page must survive its own JavaScript failing.

The whole argument for this site is that the pages are static, crawlable and
identical for every reader. Adding React is only safe if the upgrade is strictly
additive, so these tests are about what remains true when the bundle never
loads: the graph is still in the markup, the fallback is still visible, and the
page is still a page.
"""
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import export_json
import render
import test_pipeline

BREAKOUT = '</script><script>alert(1)</script>'


def check(cond, msg):
    if not cond:
        print(f"  FAIL: {msg}")
        return 1
    return 0


def main() -> int:
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved = (export_json.OUT, export_json.DB_PATH, render.DATA, render.SITE)
    try:
        dbp = tmp / "t.db"
        conn = test_pipeline.build_corpus(dbp)
        # A title that would end the JSON block early if it were not escaped.
        conn.execute("UPDATE work SET title = ? WHERE id = 'W1'", (BREAKOUT,))
        conn.commit()
        conn.close()

        export_json.OUT = tmp / "data"
        export_json.DB_PATH = dbp
        bad += check(export_json.main() == 0, "export failed")
        render.DATA = tmp / "data"
        render.SITE = tmp / "site"
        bad += check(render.main() == 0, "render failed")

        work = (tmp / "site" / "w" / "W1" / "index.html").read_text()
        author = (tmp / "site" / "a" / "A11" / "index.html").read_text()

        for name, html in (("work", work), ("author", author)):
            bad += check('data-island=' in html, f"{name} page has no island mount point")
            bad += check('class="island-mount"' in html, f"{name} page has no mount container")
            bad += check('class="static-graph"' in html, f"{name} page dropped the SVG fallback")
            bad += check("<svg" in html, f"{name} page ships no server-rendered SVG")
            bad += check("assets/islands.js" in html, f"{name} page does not load the bundle")
            # `defer` is what keeps the upgrade off the critical path. Without it
            # a 265 kB bundle blocks the parser on a page that is already
            # complete without it.
            bad += check(
                re.search(r'<script src="[^"]*islands\.js" defer>', html) is not None,
                f"{name} page loads the bundle without defer",
            )

        # THE BREAKOUT TEST. An unescaped `</script>` inside the JSON payload
        # ends the block early and the rest of the title becomes live markup.
        bad += check(
            "</script><script>alert(1)</script>" not in work,
            "A TITLE BROKE OUT OF THE JSON BLOCK INTO EXECUTABLE MARKUP",
        )
        blob = re.search(
            r'<script type="application/json" class="graph-data">(.*?)</script>', work, re.S
        )
        bad += check(blob is not None, "no graph payload on the work page")
        if blob:
            payload = json.loads(blob.group(1))
            for key in ("kind", "focus", "href_prefix", "nodes", "edges", "width", "height"):
                bad += check(key in payload, f"payload is missing {key}")
            bad += check(payload["kind"] == "citation", "work payload is not a citation graph")
            bad += check(payload["focus"] == "W1", "work payload names the wrong focus")
            # The island builds hrefs from this prefix; if it is wrong every
            # node in the graph links to a 404 and nothing else would catch it.
            for node in payload["nodes"]:
                if node["id"] == payload["focus"]:
                    continue
                target = (
                    tmp / "site" / "w" / "W1" / payload["href_prefix"] / node["id"] / "index.html"
                ).resolve()
                bad += check(target.exists(), f"island href misses {node['id']}")
            titles = {n["label"] for n in payload["nodes"]}
            bad += check(BREAKOUT in titles, "the payload lost the title it was meant to carry")

        author_blob = re.search(
            r'<script type="application/json" class="graph-data">(.*?)</script>', author, re.S
        )
        if author_blob:
            payload = json.loads(author_blob.group(1))
            bad += check(payload["kind"] == "collaboration", "author payload is not a collaboration graph")

        # The committed bundle must match its sources. Same check the gate runs,
        # asserted here so a builder that edits web/app/src sees it fail in the
        # test list rather than only in a shell step.
        sys.path.insert(0, str(Path(__file__).parent / "tools"))
        import bundle_hash  # noqa: E402

        bad += check(bundle_hash.main([]) == 0, "the committed island bundle is stale")
    finally:
        (export_json.OUT, export_json.DB_PATH, render.DATA, render.SITE) = saved
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_islands:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
