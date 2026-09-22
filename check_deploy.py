#!/usr/bin/env python3
"""Compare a deployed Who Cited It site with the checked-in static render."""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, TextIO
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree


ROOT = Path(__file__).parent
SITE = ROOT / "web" / "site"
ASSETS = ROOT / "web" / "assets"
READER_ASSETS = ("style.css", "app.js", "islands.js")
READER_DATA = (
    "search-index.json",
    "works-index.json",
    "authors-index.json",
    "institutions-index.json",
    "topics-index.json",
)
WORK_DOWNLOADS = ("citation.bib", "citation.ris")
DETAIL_PREFIXES = ("w", "a", "i", "t")


@dataclass
class Response:
    status: int
    body: bytes


Transport = Callable[[str], Response]


def stdlib_transport(url: str) -> Response:
    """Fetch one URL, leaving network failures visible to the caller."""
    request = Request(url, headers={"User-Agent": "who-cited-it-deploy-check"})
    try:
        with urlopen(request, timeout=15) as response:
            return Response(response.status, response.read())
    except HTTPError as error:
        return Response(error.code, error.read())


class TitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.parts.append(data)


def title(html: bytes) -> str | None:
    parser = TitleParser()
    parser.feed(html.decode("utf-8", errors="replace"))
    value = " ".join("".join(parser.parts).split())
    return value or None


def sha256_comparison(local: bytes, remote: bytes) -> tuple[bool, str, str]:
    """Return whether byte content matches alongside hashes suitable for a report."""
    local_hash = hashlib.sha256(local).hexdigest()
    remote_hash = hashlib.sha256(remote).hexdigest()
    return local_hash == remote_hash, local_hash, remote_hash


def sitemap_routes(sitemap: bytes) -> list[str]:
    root = ElementTree.fromstring(sitemap)
    return [urlsplit(node.text or "").path for node in root.iter() if node.tag.endswith("loc")]


def sitemap_route_diff(local: list[str], remote: list[str]) -> tuple[list[str], list[str]]:
    """Return sorted local-only and remote-only routes so the diff is order-independent."""
    local_set, remote_set = set(local), set(remote)
    return sorted(local_set - remote_set), sorted(remote_set - local_set)


def describe_route_diff(local_only: list[str], remote_only: list[str]) -> str:
    return f"local-only {', '.join(local_only) or 'none'}; remote-only {', '.join(remote_only) or 'none'}"


def local_page(site: Path, route: str) -> Path:
    if route == "/":
        return site / "index.html"
    return site / route.strip("/") / "index.html"


def detail_samples(routes: list[str]) -> dict[str, str | None]:
    samples: dict[str, str | None] = {}
    for prefix in DETAIL_PREFIXES:
        marker = f"/{prefix}/"
        samples[prefix] = next((route for route in routes if route.startswith(marker)), None)
    return samples


def print_table(rows: list[tuple[str, str, str]], stream: TextIO) -> None:
    width = max(len("CHECK"), *(len(name) for name, _, _ in rows))
    print(f"{'CHECK':<{width}}  STATUS  DETAIL", file=stream)
    print(f"{'-' * width}  ------  ------", file=stream)
    for name, status, detail in rows:
        print(f"{name:<{width}}  {status:<6}  {detail}", file=stream)


def check_deploy(
    base_url: str,
    site: Path = SITE,
    assets: Path = ASSETS,
    transport: Transport = stdlib_transport,
    stream: TextIO = sys.stdout,
) -> int:
    """Print a deployment parity table and return its shell-friendly status."""
    rows: list[tuple[str, str, str]] = []
    failures = False
    unreachable = False
    base_url = base_url.rstrip("/")

    try:
        local_sitemap = (site / "sitemap.xml").read_bytes()
        routes = sitemap_routes(local_sitemap)
    except (OSError, ElementTree.ParseError) as error:
        routes = []
        failures = True
        rows.append(("Local sitemap", "FAIL", str(error)))

    samples = detail_samples(routes)
    requested = [
        ("robots.txt", "/robots.txt"),
        ("sitemap.xml", "/sitemap.xml"),
        ("/", "/"),
        ("/methodology/", "/methodology/"),
    ]
    for prefix in DETAIL_PREFIXES:
        route = samples[prefix]
        if route is None:
            rows.append((f"HTML SHA-256 /{prefix}/ detail", "SKIP", "no local sitemap sample"))
        else:
            requested.append((route, route))
    work_route = samples["w"]
    if work_route is None:
        for download_name in WORK_DOWNLOADS:
            rows.append((f"Download SHA-256 /w/ {download_name}", "SKIP", "no local sitemap sample"))
    else:
        for download_name in WORK_DOWNLOADS:
            download_route = work_route + download_name
            requested.append((download_route, download_route))
    for asset_name in READER_ASSETS:
        asset_route = f"/assets/{asset_name}"
        requested.append((asset_route, asset_route))
    for data_name in READER_DATA:
        data_route = f"/data/{data_name}"
        requested.append((data_route, data_route))

    remote: dict[str, Response] = {}
    for label, route in requested:
        url = base_url + route
        try:
            response = transport(url)
        except OSError as error:
            rows.append((f"HTTP {label}", "FAIL", f"unreachable: {error}"))
            unreachable = True
            continue
        remote[route] = response
        if 200 <= response.status < 300:
            rows.append((f"HTTP {label}", "PASS", str(response.status)))
        else:
            rows.append((f"HTTP {label}", "FAIL", str(response.status)))
            failures = True

    remote_sitemap = remote.get("/sitemap.xml")
    if remote_sitemap is None:
        rows.append(("Sitemap route set", "FAIL", "not fetched"))
    elif not 200 <= remote_sitemap.status < 300:
        rows.append(("Sitemap route set", "FAIL", "remote sitemap unavailable"))
    else:
        try:
            local_only, remote_only = sitemap_route_diff(routes, sitemap_routes(remote_sitemap.body))
            if local_only or remote_only:
                rows.append(("Sitemap route set", "FAIL", describe_route_diff(local_only, remote_only)))
                failures = True
            else:
                rows.append(("Sitemap route set", "PASS", f"{len(set(routes))} routes match"))
        except ElementTree.ParseError as error:
            rows.append(("Sitemap route set", "FAIL", f"invalid remote sitemap: {error}"))
            failures = True

    for route in ["/", "/methodology/"]:
        response = remote.get(route)
        page = local_page(site, route)
        name = f"HTML SHA-256 {route}"
        if response is None or not 200 <= response.status < 300:
            rows.append((name, "FAIL", "remote page unavailable"))
            failures = True
        elif not page.exists():
            rows.append((name, "FAIL", f"missing local {page.relative_to(site)}"))
            failures = True
        else:
            matches, local_hash, remote_hash = sha256_comparison(page.read_bytes(), response.body)
            status = "PASS" if matches else "FAIL"
            rows.append((name, status, f"local {local_hash}; remote {remote_hash}"))
            failures |= status == "FAIL"

    for route in [sample for sample in samples.values() if sample]:
        response = remote.get(route)
        page = local_page(site, route)
        name = f"HTML SHA-256 {route}"
        if response is None or not 200 <= response.status < 300:
            rows.append((name, "FAIL", "remote page unavailable"))
            failures = True
        elif not page.exists():
            rows.append((name, "FAIL", f"missing local {page.relative_to(site)}"))
            failures = True
        else:
            matches, local_hash, remote_hash = sha256_comparison(page.read_bytes(), response.body)
            status = "PASS" if matches else "FAIL"
            rows.append((name, status, f"local {local_hash}; remote {remote_hash}"))
            failures |= status == "FAIL"

    if work_route is not None:
        for download_name in WORK_DOWNLOADS:
            download_route = work_route + download_name
            download_path = site / download_route.strip("/")
            name = f"Download SHA-256 {download_route}"
            remote_download = remote.get(download_route)
            if remote_download is None or not 200 <= remote_download.status < 300:
                rows.append((name, "FAIL", "remote download unavailable"))
                failures = True
            elif not download_path.exists():
                rows.append((name, "FAIL", f"missing local {download_path.relative_to(site)}"))
                failures = True
            else:
                matches, local_hash, remote_hash = sha256_comparison(
                    download_path.read_bytes(), remote_download.body,
                )
                status = "PASS" if matches else "FAIL"
                rows.append((name, status, f"local {local_hash}; remote {remote_hash}"))
                failures |= status == "FAIL"

    for asset_name in READER_ASSETS:
        asset_route = f"/assets/{asset_name}"
        asset_path = assets / asset_name
        name = f"Asset SHA-256 {asset_route}"
        remote_asset = remote.get(asset_route)
        if remote_asset is None or not 200 <= remote_asset.status < 300:
            rows.append((name, "FAIL", "remote asset unavailable"))
            failures = True
        elif not asset_path.exists():
            rows.append((name, "FAIL", f"missing local {asset_path}"))
            failures = True
        else:
            matches, local_hash, remote_hash = sha256_comparison(asset_path.read_bytes(), remote_asset.body)
            status = "PASS" if matches else "FAIL"
            rows.append((name, status, f"local {local_hash}; remote {remote_hash}"))
            failures |= status == "FAIL"

    for data_name in READER_DATA:
        data_route = f"/data/{data_name}"
        data_path = site / "data" / data_name
        name = f"Data SHA-256 {data_route}"
        remote_data = remote.get(data_route)
        if remote_data is None or not 200 <= remote_data.status < 300:
            rows.append((name, "FAIL", "remote data unavailable"))
            failures = True
        elif not data_path.exists():
            rows.append((name, "FAIL", f"missing local {data_path.relative_to(site)}"))
            failures = True
        else:
            matches, local_hash, remote_hash = sha256_comparison(data_path.read_bytes(), remote_data.body)
            status = "PASS" if matches else "FAIL"
            rows.append((name, status, f"local {local_hash}; remote {remote_hash}"))
            failures |= status == "FAIL"

    exit_code = 2 if unreachable else 1 if failures else 0
    rows.append(("Deployment parity", "PASS" if exit_code == 0 else "FAIL", f"exit {exit_code}"))
    print_table(rows, stream)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: check_deploy.py BASE_URL", file=sys.stderr)
        return 2
    return check_deploy(args[0])


if __name__ == "__main__":
    raise SystemExit(main())
