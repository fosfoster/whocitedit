#!/usr/bin/env python3
"""Offline coverage for render_csl_json() wiring work_csl_json() end-to-end."""
import inspect
import json
import sys

import render


# The whole CSL-JSON surface this site emits. Anything outside it in an
# artifact is a field leaking out of the export for another purpose.
CSL_FIELDS = {"id", "title", "type", "author", "issued", "container-title", "DOI"}

ABSTRACT_SENTINEL = "CSL_ABSTRACT_MUST_NOT_APPEAR"
OTHER_SOURCE_SENTINEL = "CSL_OTHER_SOURCE_MUST_NOT_APPEAR"


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def main() -> int:
    bad = 0

    # Shaped like an exported work: the bibliographic fields CSL wants, beside
    # the abstract and the identifiers carried for other parts of the site.
    work = {
        "id": "W1",
        "title": "A Fully Populated Work",
        "type": "article",
        "date": "2024-02-03",
        "year": 2024,
        "source": {"id": "S1", "name": "Journal of Examples"},
        "doi": "https://doi.org/10.1000/example",
        "authors": [{"name": "First Author"}, {"name": "Second Author"}],
        "abstract": {"text": ABSTRACT_SENTINEL, "reason": "rendered"},
        "oa": {"is_oa": True, "url": OTHER_SOURCE_SENTINEL, "license": OTHER_SOURCE_SENTINEL},
        "openalex_url": OTHER_SOURCE_SENTINEL,
        "raw": OTHER_SOURCE_SENTINEL,
        "cited_by_count": 7,
    }

    rendered = render.render_csl_json(work)
    item = json.loads(rendered)

    bad += check(item == render.work_csl_json(work),
                 "render_csl_json does not serialize render.work_csl_json's own output")

    # The acceptance surface for this ticket: id, title, type, author, issued
    # date-parts, container-title and DOI, all reached through work_csl_json()
    # rather than a second, parallel derivation in render_csl_json() itself.
    bad += check(item["id"] == "W1", "id was not passed through")
    bad += check(item["title"] == "A Fully Populated Work", "title was not passed through")
    bad += check(item["type"] == "article-journal",
                 "type was not mapped through the CSL type-mapping helper")
    bad += check(item["author"] == [{"literal": "First Author"}, {"literal": "Second Author"}],
                 "authors were not rendered as CSL literal names")
    bad += check(item["issued"] == {"date-parts": [[2024, 2, 3]]},
                 "issued date-parts were not derived from the full date")
    bad += check(item["container-title"] == "Journal of Examples",
                 "container-title was not derived from the source name")
    bad += check(item["DOI"] == "10.1000/example",
                 "DOI was not reduced to a bare DOI")

    # The abstract is licence-gated on the work page itself, and nothing
    # sourced from outside the citation metadata belongs in an import handed to
    # a citation manager.
    bad += check(set(item) <= CSL_FIELDS,
                 f"artifact carries fields outside the CSL surface: {sorted(set(item) - CSL_FIELDS)}")
    bad += check(ABSTRACT_SENTINEL not in rendered, "the artifact leaked the abstract sentinel")
    bad += check(OTHER_SOURCE_SENTINEL not in rendered,
                 "the artifact leaked an unrelated-source sentinel")

    # render_csl_json() must not carry its own, parallel date/DOI derivation --
    # tkt_fc1d910f5e0d's cancelled attempt at this ticket did exactly that, with
    # its own bare_doi/csl_date_parts helpers duplicating #57's _csl_issued and
    # _csl_doi. Hold the module to one implementation of each by looking at the
    # source, since two agreeing implementations pass any output-only check.
    module_source = inspect.getsource(render)
    elsewhere = module_source.replace(inspect.getsource(render._csl_issued), "")
    bad += check("date-parts" not in elsewhere,
                 "a second date-parts derivation lives outside _csl_issued")
    elsewhere = module_source.replace(inspect.getsource(render._csl_doi), "")
    bad += check("normalize_doi(" not in elsewhere,
                 "a second DOI derivation lives outside _csl_doi")
    bad += check("work_csl_json(" in inspect.getsource(render.render_csl_json),
                 "render_csl_json does not call work_csl_json")
    bad += check("csl_type(" in inspect.getsource(render.work_csl_json),
                 "work_csl_json does not map the work type through csl_type")

    no_doi_work = {**work, "doi": None}
    no_doi_item = json.loads(render.render_csl_json(no_doi_work))
    bad += check("DOI" not in no_doi_item, "a work without a DOI emitted a DOI field")

    # A work with nothing but an id still has to be a valid CSL item, and an
    # unrecognised type still has to land on the document fallback.
    sparse = {"id": "W2", "type": "not-a-real-type", "abstract": {"text": ABSTRACT_SENTINEL}}
    sparse_rendered = render.render_csl_json(sparse)
    sparse_item = json.loads(sparse_rendered)
    bad += check(sparse_item == {"id": "W2", "type": "document"},
                 f"a sparse work fabricated fields: {sorted(sparse_item)}")
    bad += check(ABSTRACT_SENTINEL not in sparse_rendered,
                 "a sparse work's artifact leaked the abstract sentinel")

    print("test_csl_json:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
