from __future__ import annotations

import argparse
import re
import time
from collections import deque

import requests
from selectolax.parser import HTMLParser

from tatemono_map.db.repo import connect, insert_raw_source
from tatemono_map.ingest.ulucks_playwright import fetch_pages_with_playwright

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; tatemono-map/1.0)",
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
}
ERROR_MARKER = "このリストは存在しません"
ROOT_SMARTLINK_RE = re.compile(r"^https?://[^/]+/view/smartlink/?$")
ORIGIN_RE = re.compile(r"^(https?://[^/]+)")


def _origin_of(url: str) -> str | None:
    m = ORIGIN_RE.match(url)
    return m.group(1) if m else None


def _to_absolute_href(current_url: str, href: str) -> str | None:
    value = href.strip()
    if not value:
        return None
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("//"):
        if current_url.startswith("https://"):
            return f"https:{value}"
        if current_url.startswith("http://"):
            return f"http:{value}"
        return None
    if value.startswith("/"):
        origin = _origin_of(current_url)
        if not origin:
            return None
        return f"{origin}{value}"
    return None


def _validate_fetched_page(url: str, html: str) -> None:
    if ROOT_SMARTLINK_RE.match(url) and "?" not in url:
        raise RuntimeError(f"smartlink URL lost query and fell back to root path: {url}")
    if ERROR_MARKER in html:
        raise RuntimeError(f"smartlink returned error page marker: {url}")


def extract_pagination_hrefs(current_url: str, html: str) -> list[str]:
    tree = HTMLParser(html)
    hrefs: list[str] = []
    seen: set[str] = set()
    for anchor in tree.css("a[href]"):
        raw_href = anchor.attributes.get("href") or ""
        absolute = _to_absolute_href(current_url, raw_href)
        if not absolute:
            continue
        if "/view/smartlink" not in absolute:
            continue
        if absolute == current_url:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        hrefs.append(absolute)
    return hrefs


def _request_with_retry(url: str, timeout: float, retries: int) -> str:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, timeout=timeout, headers=DEFAULT_HEADERS)
            response.raise_for_status()
            response.encoding = response.encoding or "utf-8"
            return response.text
        except Exception as exc:  # noqa: PERF203
            last_error = exc
            if attempt == retries:
                break
            time.sleep(min(2**attempt, 5))
    if last_error is None:
        raise RuntimeError("request failed")
    raise RuntimeError(f"failed to fetch {url}: {last_error}") from last_error


def _iter_paginated_pages(seed_url: str, timeout: float, retries: int, max_pages: int) -> list[tuple[str, str]]:
    queue: deque[str] = deque([seed_url])
    visited: set[str] = set()
    pages: list[tuple[str, str]] = []

    while queue and len(pages) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        html = _request_with_retry(url, timeout=timeout, retries=retries)
        _validate_fetched_page(url, html)
        pages.append((url, html))

        for next_href in extract_pagination_hrefs(url, html):
            if next_href not in visited:
                queue.append(next_href)

    return pages


def run(url: str, db_path: str, max_items: int = 200, timeout: float = 20.0, retries: int = 2) -> int:
    try:
        pages = _iter_paginated_pages(url, timeout=timeout, retries=retries, max_pages=max_items)
    except Exception:
        pages = fetch_pages_with_playwright(url, max_pages=max_items)

    conn = connect(db_path)
    saved = 0
    for page_url, html in pages:
        _validate_fetched_page(page_url, html)
        insert_raw_source(conn, "ulucks", "smartlink_page", page_url, html)
        saved += 1
    conn.close()
    return saved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", action="append", required=True)
    parser.add_argument("--db", "--db-path", dest="db_path", default="data/tatemono_map.sqlite3")
    parser.add_argument("--limit", "--max-items", dest="max_items", type=int, default=200)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    total = 0
    for seed_url in args.url:
        total += run(seed_url, args.db_path, max_items=args.max_items, timeout=args.timeout, retries=args.retries)
    print(f"saved smartlink pages: {total}")


if __name__ == "__main__":
    main()
