#!/usr/bin/env python3
"""Offline fixtures for the deployment parity checker."""
import io
import shutil
import tempfile
from pathlib import Path

import check_deploy


BASE_URL = "https://deploy.example"
ROUTES = ("/w/W1/", "/a/A1/", "/i/I1/", "/t/T1/")


def check(condition, message):
    if not condition:
        print(f"  FAIL: {message}")
        return 1
    return 0


def html(page_title):
    return f"<!doctype html><html><head><title>{page_title}</title></head><body></body></html>".encode()


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


def main():
    bad = 0
    tmp = Path(tempfile.mkdtemp())
    saved_urlopen = check_deploy.urlopen

    def no_network(*args, **kwargs):
        raise AssertionError("test attempted a real network fetch")

    check_deploy.urlopen = no_network
    try:
        site = tmp / "site"
        pages, bundle = write_render(site)
        responses = fixture_responses(pages, bundle)
        expected_urls = {BASE_URL + route for route in (
            "/robots.txt", "/sitemap.xml", "/", "/methodology/", *ROUTES, "/assets/islands.js",
        )}

        code, output, calls = run_case(site, bundle, responses)
        bad += check(code == 0, "matching deployment did not return 0")
        bad += check(set(calls) == expected_urls and len(calls) == 9,
                     "matching deployment did not request exactly the nine resources")
        bad += check("Deployment parity" in output and "PASS" in output,
                     "matching deployment did not print a PASS table")
        for route in ("/", "/methodology/", *ROUTES):
            bad += check(f"Title {route}" in output,
                         f"matching deployment did not compare title for {route}")

        stale_sitemap = dict(responses)
        stale_sitemap["/sitemap.xml"] = sitemap(("/", "/methodology/") + ROUTES[:-1])
        code, output, _ = run_case(site, bundle, stale_sitemap)
        bad += check(code == 1 and "Sitemap URL count" in output and "FAIL" in output,
                     "stale sitemap did not return 1 with a failing sitemap row")

        wrong_title = dict(responses)
        wrong_title["/a/A1/"] = html("Old author title")
        code, output, _ = run_case(site, bundle, wrong_title)
        bad += check(code == 1 and "Title /a/A1/" in output and "Old author title" in output,
                     "title mismatch did not return 1 with the sampled title")

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

        missing = tmp / "missing-site"
        shutil.copytree(site, missing)
        shutil.rmtree(missing / "i")
        missing_routes = ("/", "/methodology/", "/w/W1/", "/a/A1/", "/t/T1/")
        (missing / "sitemap.xml").write_bytes(sitemap(missing_routes))
        missing_responses = fixture_responses(pages, bundle)
        missing_responses["/sitemap.xml"] = sitemap(missing_routes)
        code, output, calls = run_case(missing, bundle, missing_responses)
        bad += check(code == 0 and "Title /i/ detail" in output and "SKIP" in output,
                     "missing local detail class was not a non-failing SKIP")
        bad += check(BASE_URL + "/i/I1/" not in calls,
                     "checker fetched a detail route with no local sample")
    finally:
        check_deploy.urlopen = saved_urlopen
        shutil.rmtree(tmp, ignore_errors=True)

    print("test_check_deploy:", "FAILED" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
