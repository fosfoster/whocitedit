#!/usr/bin/env python3
"""Offline fixtures for the deployment parity checker."""
import hashlib
import io
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

import check_deploy


BASE_URL = "https://deploy.example"
ROUTES = ("/w/W1/", "/a/A1/", "/i/I1/", "/t/T1/")


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def html(page_title, body=""):
    return f"<!doctype html><html><head><title>{page_title}</title></head><body>{body}</body></html>".encode()


def sitemap(routes, origin=BASE_URL):
    locations = "".join(f"<url><loc>{origin}{route}</loc></url>" for route in routes)
    return f'<?xml version="1.0"?><urlset>{locations}</urlset>'.encode()


READER_ASSET_CONTENTS = {
    "style.css": b"body { color: fixture; }\n",
    "app.js": b"// fixture app bundle\n",
    "islands.js": b"fixture island bundle\n",
}
WORK_DOWNLOAD_CONTENTS = {
    "citation.bib": b"@article{W1, title={Fixture}}\n",
    "citation.ris": b"TY  - JOUR\nTI  - Fixture\nER  - \n",
}


def write_render(root):
    pages = {"/": "Home", "/methodology/": "Methodology"}
    pages.update({route: f"Detail {route}" for route in ROUTES})
    for route, page_title in pages.items():
        path = root / ("index.html" if route == "/" else route.strip("/") + "/index.html")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(html(page_title))
    for route in (route for route in ROUTES if route.startswith("/w/")):
        for download_name, content in WORK_DOWNLOAD_CONTENTS.items():
            (root / route.strip("/") / download_name).write_bytes(content)
    (root / "sitemap.xml").write_bytes(sitemap(("/", "/methodology/") + ROUTES))
    assets = root.parent / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for asset_name, content in READER_ASSET_CONTENTS.items():
        (assets / asset_name).write_bytes(content)
    return pages, assets


def fixture_responses(pages, assets):
    responses = {
        "/robots.txt": b"User-agent: *\nAllow: /\n",
        "/sitemap.xml": sitemap(("/", "/methodology/") + ROUTES),
    }
    for asset_name in READER_ASSET_CONTENTS:
        responses[f"/assets/{asset_name}"] = (assets / asset_name).read_bytes()
    responses.update({route: html(page_title) for route, page_title in pages.items()})
    for route in (route for route in ROUTES if route.startswith("/w/")):
        for download_name, content in WORK_DOWNLOAD_CONTENTS.items():
            responses[route + download_name] = content
    return responses


class FixtureTransport:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        route = url.removeprefix(BASE_URL)
        return check_deploy.Response(200, self.responses[route])


def run_case(site, assets, responses):
    transport = FixtureTransport(responses)
    output = io.StringIO()
    code = check_deploy.check_deploy(BASE_URL, site, assets, transport, output)
    return code, output.getvalue(), transport.calls


@contextmanager
def offline_fixture():
    tmp = Path(tempfile.mkdtemp())
    saved_urlopen = check_deploy.urlopen

    def no_network(*args, **kwargs):
        raise AssertionError("test attempted a real network fetch")

    check_deploy.urlopen = no_network
    try:
        site = tmp / "site"
        pages, assets = write_render(site)
        responses = fixture_responses(pages, assets)
        yield site, pages, assets, responses
    finally:
        check_deploy.urlopen = saved_urlopen
        shutil.rmtree(tmp, ignore_errors=True)


def test_shared_html_content_drift():
    bad = 0
    with offline_fixture() as (site, _, assets, responses):
        for route in ("/", "/methodology/"):
            changed_body = dict(responses)
            changed_body[route] = changed_body[route].replace(
                b"<body></body>", b"<body>stale shared content</body>",
            )
            bad += check(
                check_deploy.title(changed_body[route]) == check_deploy.title(responses[route]),
                f"content-drift fixture for {route} changed its title",
            )
            code, output, _ = run_case(site, assets, changed_body)
            row = f"HTML SHA-256 {route}"
            content_row = next((line for line in output.splitlines() if line.startswith(row)), "")
            local_hash = hashlib.sha256(responses[route]).hexdigest()
            remote_hash = hashlib.sha256(changed_body[route]).hexdigest()
            bad += check(
                code == 1 and "FAIL" in content_row
                and f"local {local_hash}; remote {remote_hash}" in content_row,
                f"same-title content drift for {route} did not fail its HTML hash comparison",
            )
    return 1 if bad else 0


def test_detail_html_content_drift():
    bad = 0
    with offline_fixture() as (site, pages, assets, responses):
        for route in ROUTES:
            changed_body = dict(responses)
            changed_body[route] = html(pages[route], f"stale detail content for {route}")
            local_title = responses[route].split(b"</title>", 1)[0]
            remote_title = changed_body[route].split(b"</title>", 1)[0]
            bad += check(
                local_title == remote_title and responses[route] != changed_body[route],
                f"content-drift fixture for {route} did not preserve its title",
            )
            code, output, _ = run_case(site, assets, changed_body)
            row = f"HTML SHA-256 {route}"
            content_row = next((line for line in output.splitlines() if line.startswith(row)), "")
            local_hash = hashlib.sha256(responses[route]).hexdigest()
            remote_hash = hashlib.sha256(changed_body[route]).hexdigest()
            bad += check(
                code == 1 and "FAIL" in content_row
                and f"local {local_hash}; remote {remote_hash}" in content_row,
                f"same-title content drift for {route} did not fail its HTML hash comparison",
            )
    return 1 if bad else 0


def test_sitemap_route_set_parity():
    bad = 0
    local_routes = ("/", "/methodology/") + ROUTES
    with offline_fixture() as (site, _, assets, responses):
        reordered = dict(responses)
        reordered["/sitemap.xml"] = sitemap(tuple(reversed(local_routes)), origin="https://other.example")
        bad += check(reordered["/sitemap.xml"] != responses["/sitemap.xml"],
                     "reordered sitemap fixture is byte-identical to the local sitemap")
        code, output, _ = run_case(site, assets, reordered)
        row = next((line for line in output.splitlines() if line.startswith("Sitemap route set")), "")
        bad += check(code == 0 and "PASS" in row and f"{len(local_routes)} routes match" in row,
                     "reordered sitemap with a different origin did not pass as an equal route set")

        substituted_routes = local_routes[:-1] + ("/t/T2/",)
        substituted = dict(responses)
        substituted["/sitemap.xml"] = sitemap(substituted_routes)
        bad += check(
            len(check_deploy.sitemap_routes(substituted["/sitemap.xml"])) == len(local_routes),
            "route substitution fixture changed the sitemap entry count",
        )
        code, output, _ = run_case(site, assets, substituted)
        row = next((line for line in output.splitlines() if line.startswith("Sitemap route set")), "")
        bad += check(
            code == 1 and "FAIL" in row and "local-only /t/T1/" in row and "remote-only /t/T2/" in row,
            "same-count route substitution did not fail with both differences in the sitemap row",
        )
    return 1 if bad else 0


def test_reader_critical_asset_hashes():
    bad = 0
    with offline_fixture() as (site, _, assets, responses):
        for asset_name in check_deploy.READER_ASSETS:
            route = f"/assets/{asset_name}"
            drifted = dict(responses)
            drifted[route] = responses[route] + b"tampered"
            code, output, _ = run_case(site, assets, drifted)
            row = next((line for line in output.splitlines()
                        if line.startswith(f"Asset SHA-256 {route}")), "")
            local_hash = hashlib.sha256(responses[route]).hexdigest()
            remote_hash = hashlib.sha256(drifted[route]).hexdigest()
            bad += check(
                code == 1 and "FAIL" in row and f"local {local_hash}; remote {remote_hash}" in row,
                f"drifting {asset_name} alone did not fail its asset hash row",
            )
            for other_name in check_deploy.READER_ASSETS:
                if other_name == asset_name:
                    continue
                other_route = f"/assets/{other_name}"
                other_row = next((line for line in output.splitlines()
                                   if line.startswith(f"Asset SHA-256 {other_route}")), "")
                bad += check("PASS" in other_row,
                              f"drifting {asset_name} incorrectly failed {other_name}'s hash row")

        missing_assets = site.parent / "missing-assets"
        shutil.copytree(assets, missing_assets)
        (missing_assets / "app.js").unlink()
        code, output, _ = run_case(site, missing_assets, responses)
        row = next((line for line in output.splitlines()
                    if line.startswith("Asset SHA-256 /assets/app.js")), "")
        bad += check(code == 1 and "FAIL" in row and "missing local" in row,
                     "a missing local asset did not fail with a missing-local detail")

        def bad_status_transport(url):
            if url == BASE_URL + "/assets/style.css":
                return check_deploy.Response(404, b"not found")
            return check_deploy.Response(200, responses[url.removeprefix(BASE_URL)])

        output = io.StringIO()
        code = check_deploy.check_deploy(BASE_URL, site, assets, bad_status_transport, output)
        row = next((line for line in output.getvalue().splitlines()
                    if line.startswith("Asset SHA-256 /assets/style.css")), "")
        bad += check(code == 1 and "FAIL" in row and "remote asset unavailable" in row,
                     "an unsuccessful remote response did not fail without weakening exit 2")
    return 1 if bad else 0


def main():
    bad = 0
    with offline_fixture() as (site, pages, assets, responses):
        expected_urls = {BASE_URL + route for route in (
            "/robots.txt", "/sitemap.xml", "/", "/methodology/", *ROUTES,
            "/w/W1/citation.bib", "/w/W1/citation.ris",
            "/assets/style.css", "/assets/app.js", "/assets/islands.js",
        )}

        code, output, calls = run_case(site, assets, responses)
        bad += check(code == 0, "matching deployment did not return 0")
        bad += check(set(calls) == expected_urls and len(calls) == 13,
                     "matching deployment did not request exactly the thirteen resources")
        bad += check("Deployment parity" in output and "PASS" in output,
                     "matching deployment did not print a PASS table")
        for download_name in check_deploy.WORK_DOWNLOADS:
            row = next((line for line in output.splitlines()
                        if line.startswith(f"HTTP /w/W1/{download_name}")), "")
            bad += check("PASS" in row and "200" in row,
                         f"matching deployment did not pass {download_name}'s HTTP row")
        for route in ("/", "/methodology/"):
            row = next((line for line in output.splitlines()
                        if line.startswith(f"HTML SHA-256 {route}")), "")
            content_hash = hashlib.sha256(responses[route]).hexdigest()
            bad += check(
                "PASS" in row and f"local {content_hash}; remote {content_hash}" in row,
                f"matching deployment did not report matching HTML hashes for {route}",
            )
        for route in ROUTES:
            row = next((line for line in output.splitlines()
                        if line.startswith(f"HTML SHA-256 {route}")), "")
            content_hash = hashlib.sha256(responses[route]).hexdigest()
            bad += check(
                "PASS" in row and f"local {content_hash}; remote {content_hash}" in row,
                f"matching deployment did not report matching HTML hashes for {route}",
            )

        stale_sitemap = dict(responses)
        stale_sitemap["/sitemap.xml"] = sitemap(("/", "/methodology/") + ROUTES[:-1])
        code, output, _ = run_case(site, assets, stale_sitemap)
        bad += check(code == 1 and "Sitemap route set" in output and "FAIL" in output,
                     "stale sitemap did not return 1 with a failing sitemap row")

        changed_author_html = dict(responses)
        changed_author_html["/a/A1/"] = html("Old author title")
        code, output, _ = run_case(site, assets, changed_author_html)
        bad += check(code == 1 and "HTML SHA-256 /a/A1/" in output and "FAIL" in output,
                     "detail HTML mismatch did not return 1 with a hash row")

        def missing_ris(url):
            route = url.removeprefix(BASE_URL)
            if route == "/w/W1/citation.ris":
                return check_deploy.Response(404, b"not found")
            return check_deploy.Response(200, responses[route])

        output = io.StringIO()
        code = check_deploy.check_deploy(BASE_URL, site, assets, missing_ris, output)
        bib_row = next((line for line in output.getvalue().splitlines()
                        if line.startswith("HTTP /w/W1/citation.bib")), "")
        ris_row = next((line for line in output.getvalue().splitlines()
                        if line.startswith("HTTP /w/W1/citation.ris")), "")
        bad += check(code == 1 and "PASS" in bib_row and "FAIL" in ris_row and "404" in ris_row,
                     "a missing work citation download did not report its HTTP failure")

        stale_bundle = dict(responses)
        stale_bundle["/assets/islands.js"] = b"old fixture island bundle\n"
        code, output, _ = run_case(site, assets, stale_bundle)
        bad += check(code == 1 and "Asset SHA-256 /assets/islands.js" in output and "FAIL" in output,
                     "stale islands.js did not return 1 with an asset hash row")

        calls = []
        def unreachable(url):
            calls.append(url)
            raise OSError("fixture host is unreachable")

        output = io.StringIO()
        code = check_deploy.check_deploy(BASE_URL, site, assets, unreachable, output)
        bad += check(code == 2 and len(calls) == 13 and "Deployment parity" in output.getvalue(),
                     "unreachable host did not return 2 with a complete table")

        missing = site.parent / "missing-site"
        shutil.copytree(site, missing)
        shutil.rmtree(missing / "i")
        missing_routes = ("/", "/methodology/", "/w/W1/", "/a/A1/", "/t/T1/")
        (missing / "sitemap.xml").write_bytes(sitemap(missing_routes))
        missing_responses = fixture_responses(pages, assets)
        missing_responses["/sitemap.xml"] = sitemap(missing_routes)
        code, output, calls = run_case(missing, assets, missing_responses)
        bad += check(code == 0 and "HTML SHA-256 /i/ detail" in output and "SKIP" in output,
                     "missing local detail class was not a non-failing SKIP")
        bad += check(BASE_URL + "/i/I1/" not in calls,
                     "checker fetched a detail route with no local sample")

        no_work = site.parent / "no-work-site"
        shutil.copytree(site, no_work)
        shutil.rmtree(no_work / "w")
        no_work_routes = ("/", "/methodology/", "/a/A1/", "/i/I1/", "/t/T1/")
        (no_work / "sitemap.xml").write_bytes(sitemap(no_work_routes))
        no_work_responses = fixture_responses(pages, assets)
        no_work_responses["/sitemap.xml"] = sitemap(no_work_routes)
        code, output, calls = run_case(no_work, assets, no_work_responses)
        download_skips = [
            next((line for line in output.splitlines()
                  if line.startswith(f"Download SHA-256 /w/ {download_name}")), "")
            for download_name in check_deploy.WORK_DOWNLOADS
        ]
        download_urls = [BASE_URL + "/w/W1/" + download_name
                         for download_name in check_deploy.WORK_DOWNLOADS]
        bad += check(code == 0 and all(
            "SKIP" in row and "no local sitemap sample" in row for row in download_skips
        ),
                     "missing local work sample did not produce non-failing download SKIP rows")
        bad += check(not any(url in calls for url in download_urls),
                     "checker fetched work downloads with no local work sample")

    bad += test_shared_html_content_drift()
    bad += test_detail_html_content_drift()
    bad += test_sitemap_route_set_parity()
    bad += test_reader_critical_asset_hashes()

    print("test_check_deploy:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
