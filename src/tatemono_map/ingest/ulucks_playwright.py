from __future__ import annotations

import re
from dataclasses import dataclass

from selectolax.parser import HTMLParser

ERROR_MARKERS = (
    "このリストは存在しません",
    "ログイン",
    "認証",
    "セッション",
)
VALID_MARKERS = ("家賃", "所在地", "間取り")
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


def _extract_pagination_hrefs(current_url: str, html: str) -> list[str]:
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


@dataclass(frozen=True)
class FetchResult:
    url: str
    is_valid: bool
    reason: str
    content: str


def is_valid_smartlink_html(content: str) -> tuple[bool, str]:
    lowered = content.lower()
    if any(marker in content for marker in ERROR_MARKERS) or "login" in lowered:
        return False, "error_screen"
    if any(marker in content for marker in VALID_MARKERS):
        return True, "ok"
    return False, "missing_listing_markers"


def fetch_pages_with_playwright(seed_url: str, max_pages: int = 200) -> list[tuple[str, str]]:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    pages: list[tuple[str, str]] = []
    queue = [seed_url]
    visited: set[str] = set()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        while queue and len(pages) < max_pages:
            target = queue.pop(0)
            if target in visited:
                continue
            visited.add(target)

            try:
                page.goto(target, wait_until="networkidle", timeout=45_000)
            except PlaywrightTimeoutError:
                page.goto(target, wait_until="domcontentloaded", timeout=45_000)
            html = page.content()
            pages.append((target, html))
            for href in _extract_pagination_hrefs(target, html):
                if href not in visited:
                    queue.append(href)

        context.close()
        browser.close()

    return pages
