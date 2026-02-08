from __future__ import annotations

import argparse
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from selectolax.parser import HTMLParser

from tatemono_map.db.repo import connect, insert_raw_source


def _with_page(url: str, page: int) -> str:
    parsed = urlparse(url)
    qs = dict(parse_qsl(parsed.query, keep_blank_values=True))
    qs["page"] = str(page)
    return urlunparse(parsed._replace(query=urlencode(qs)))


def fetch_text(url: str, timeout: float = 20.0) -> str:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "tatemono-map/1.0"})
    r.raise_for_status()
    return r.text


def _has_listing_cards(html: str) -> bool:
    tree = HTMLParser(html)
    if tree.css("article.property-card"):
        return True
    return bool(tree.css('dt:contains("所在地")') or tree.css('th:contains("所在地")'))


def run(url: str, db_path: str, max_items: int = 200) -> int:
    conn = connect(db_path)
    seen_bodies: set[str] = set()
    saved = 0

    for page in range(1, max_items + 1):
        page_url = _with_page(url, page)
        html = fetch_text(page_url)
        body_sig = html.strip()
        if body_sig in seen_bodies:
            break
        seen_bodies.add(body_sig)

        if not _has_listing_cards(html):
            break

        insert_raw_source(conn, "ulucks", "smartlink_page", page_url, html)
        saved += 1

    conn.close()
    return saved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--db-path", default="data/tatemono_map.sqlite3")
    parser.add_argument("--max-items", type=int, default=200)
    args = parser.parse_args()
    n = run(args.url, args.db_path, args.max_items)
    print(f"saved smartlink pages: {n}")


if __name__ == "__main__":
    main()
