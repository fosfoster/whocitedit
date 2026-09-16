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


def sitemap(routes):
    locations = "".join(f"<url><loc>{BASE_URL}{route}</loc></url>" for route in routes)
    return f'<?xml version="1.0"?><urlset>{locations}</urlset>'.encode()


def write_render(root):
    pages = {"/": "Home", "/methodology/": "Methodology"}
    pages.update({route: f"Detail {route}" for route in ROUTES})
    for route, page_title in pages.items():
        path = root / ("index.html" if route == "/" else route.strip("/") + "/index.html")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(html(page_title))
    (root / "sitemap.xml").write_bytes(sitemap(("/", "/methodology/") + ROUTES))
    bundle = root.parent / "islands.js"
    bundle.write_bytes(b"fixture island bundle\n")
    return pages, bundle


def fixture_responses(pages, bundle):
    responses = {
        "/robots.txt": b"User-agent: *\nAllow: /\n",
        "/sitemap.xml": sitemap(("/", "/methodology/") + ROUTES),
        "/assets/islands.js": bundle.read_bytes(),
    }
    responses.update({route: html(page_title) for route, page_title in pages.items()})
    return responses


class FixtureTransport:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        route = url.removeprefix(BASE_URL)
        return check_deploy.Response(200, self.responses[route])


def run_case(site, bundle, responses):
    transport = FixtureTransport(responses)
    output = io.StringIO()
    code = check_deploy.check_deploy(BASE_URL, site, bundle, transport, output)
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
        pages, bundle = write_render(site)
        responses = fixture_responses(pages, bundle)
        yield site, pages, bundle, responses
    finally:
        check_deploy.urlopen = saved_urlopen
        shutil.rmtree(tmp, ignore_errors=True)


def test_shared_html_content_drift():
    bad = 0
    with offline_fixture() as (site, _, bundle, responses):
        for route in ("/", "/methodology/"):
            changed_body = dict(responses)
            changed_body[route] = changed_body[route].replace(
                b"<body></body>", b"<body>stale shared content</body>",
            )
            bad += check(
                check_deploy.title(changed_body[route]) == check_deploy.title(responses[route]),
                f"content-drift fixture for {route} changed its title",
            )
            code, output, _ = run_case(site, bundle, changed_body)
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
    with offline_fixture() as (site, pages, bundle, responses):
        for route in ROUTES:
            changed_body = dict(responses)
            changed_body[route] = html(pages[route], f"stale detail content for {route}")
            local_title = responses[route].split(b"</title>", 1)[0]
            remote_title = changed_body[route].split(b"</title>", 1)[0]
            bad += check(
                local_title == remote_title and responses[route] != changed_body[route],
                f"content-drift fixture for {route} did not preserve its title",
            )
            code, output, _ = run_case(site, bundle, changed_body)
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


def main():
    bad = 0
    with offline_fixture() as (site, pages, bundle, responses):
        expected_urls = {BASE_URL + route for route in (
            "/robots.txt", "/sitemap.xml", "/", "/methodology/", *ROUTES, "/assets/islands.js",
        )}

        code, output, calls = run_case(site, bundle, responses)
        bad += check(code == 0, "matching deployment did not return 0")
        bad += check(set(calls) == expected_urls and len(calls) == 9,
                     "matching deployment did not request exactly the nine resources")
        bad += check("Deployment parity" in output and "PASS" in output,
                     "matching deployment did not print a PASS table")
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
        code, output, _ = run_case(site, bundle, stale_sitemap)
        bad += check(code == 1 and "Sitemap URL count" in output and "FAIL" in output,
                     "stale sitemap did not return 1 with a failing sitemap row")

        changed_author_html = dict(responses)
        changed_author_html["/a/A1/"] = html("Old author title")
        code, output, _ = run_case(site, bundle, changed_author_html)
        bad += check(code == 1 and "HTML SHA-256 /a/A1/" in output and "FAIL" in output,
                     "detail HTML mismatch did not return 1 with a hash row")

        stale_bundle = dict(responses)
        stale_bundle["/assets/islands.js"] = b"old fixture island bundle\n"
        code, output, _ = run_case(site, bundle, stale_bundle)
        bad += check(code == 1 and "Bundle SHA-256" in output and "FAIL" in output,
                     "stale bundle did not return 1 with a bundle row")

        calls = []
        def unreachable(url):
            calls.append(url)
            raise OSError("fixture host is unreachable")

        output = io.StringIO()
        code = check_deploy.check_deploy(BASE_URL, site, bundle, unreachable, output)
        bad += check(code == 2 and len(calls) == 9 and "Deployment parity" in output.getvalue(),
                     "unreachable host did not return 2 with a complete table")

        missing = site.parent / "missing-site"
        shutil.copytree(site, missing)
        shutil.rmtree(missing / "i")
        missing_routes = ("/", "/methodology/", "/w/W1/", "/a/A1/", "/t/T1/")
        (missing / "sitemap.xml").write_bytes(sitemap(missing_routes))
        missing_responses = fixture_responses(pages, bundle)
        missing_responses["/sitemap.xml"] = sitemap(missing_routes)
        code, output, calls = run_case(missing, bundle, missing_responses)
        bad += check(code == 0 and "HTML SHA-256 /i/ detail" in output and "SKIP" in output,
                     "missing local detail class was not a non-failing SKIP")
        bad += check(BASE_URL + "/i/I1/" not in calls,
                     "checker fetched a detail route with no local sample")

    bad += test_shared_html_content_drift()
    bad += test_detail_html_content_drift()

    print("test_check_deploy:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
