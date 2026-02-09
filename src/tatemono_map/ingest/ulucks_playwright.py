from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


ERROR_MARKERS = (
    "このリストは存在しません",
    "ログイン",
    "認証",
    "セッション",
)
VALID_MARKERS = ("家賃", "所在地", "間取り")


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


def _page_url(seed_url: str, page: int) -> str:
    parsed = urlparse(seed_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["sort"] = "1"
    query_str = urlencode(query)
    path = f"/view/smartlink/page:{page}/sort:Rent.modified/direction:desc"
    return urlunparse(parsed._replace(path=path, query=query_str))


def _raw_sources_columns(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("PRAGMA table_info(raw_sources)").fetchall()
    return {row[1] for row in rows}


def upsert_raw_source(
    conn: sqlite3.Connection,
    provider: str,
    source_kind: str,
    source_url: str,
    content: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    columns = _raw_sources_columns(conn)
    provider_col = "provider" if "provider" in columns else "source_system"

    existing = conn.execute(
        "SELECT id FROM raw_sources WHERE source_kind=? AND source_url=? ORDER BY id DESC LIMIT 1",
        (source_kind, source_url),
    ).fetchone()

    if existing:
        conn.execute(
            f"UPDATE raw_sources SET {provider_col}=?, content=?, fetched_at=? WHERE id=?",
            (provider, content, now, existing[0]),
        )
    else:
        conn.execute(
            f"INSERT INTO raw_sources({provider_col}, source_kind, source_url, content, fetched_at) VALUES (?, ?, ?, ?, ?)",
            (provider, source_kind, source_url, content, now),
        )
    conn.commit()


def init_auth_state(auth_file: str) -> None:
    from playwright.sync_api import sync_playwright

    path = Path(auth_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://kitakyushu.ulucks.jp/view/smartlink/", wait_until="domcontentloaded")
        input("ブラウザでログイン後、Enterを押すと storage_state を保存します... ")
        context.storage_state(path=str(path))
        context.close()
        browser.close()


def _fetch_page(page, url: str) -> FetchResult:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    try:
        page.goto(url, wait_until="networkidle", timeout=45_000)
    except PlaywrightTimeoutError:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    content = page.content()
    valid, reason = is_valid_smartlink_html(content)
    return FetchResult(url=url, is_valid=valid, reason=reason, content=content)


def fetch_seed(seed_url: str, auth_file: str, db_path: str, max_pages: int = 200) -> int:
    from playwright.sync_api import sync_playwright

    auth_path = Path(auth_file)
    if not auth_path.exists():
        raise FileNotFoundError(f"auth file not found: {auth_file}")

    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_file)
    saved = 0
    seen_hashes: set[str] = set()
    stagnant = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(auth_path))
        page = context.new_page()

        for index in range(1, max_pages + 1):
            target_url = _page_url(seed_url, index)
            result = _fetch_page(page, target_url)

            digest = hashlib.sha1(result.content.encode("utf-8")).hexdigest()
            if digest in seen_hashes:
                print(f"stop: repeated_html page={index} url={target_url}")
                break
            seen_hashes.add(digest)

            if not result.is_valid:
                stagnant += 1
                print(f"skip: page={index} reason={result.reason} url={target_url}")
                if index == 1 or stagnant >= 2:
                    break
                continue

            stagnant = 0
            upsert_raw_source(conn, "ulucks", "smartlink_page", target_url, result.content)
            saved += 1
            print(f"saved: page={index} url={target_url}")

        context.close()
        browser.close()

    conn.close()
    return saved
