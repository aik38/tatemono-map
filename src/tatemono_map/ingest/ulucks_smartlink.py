from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from selectolax.parser import HTMLParser

from tatemono_map.db.repo import ListingRecord, connect, insert_raw_source, upsert_listing
from tatemono_map.parse.ulucks_smartview import parse_smartview_html


def collect_smartview_links(smartlink_html: str, base_url: str) -> list[str]:
    tree = HTMLParser(smartlink_html)
    links: list[str] = []
    for a in tree.css('a[href*="/view/smartview/"]'):
        href = a.attributes.get("href", "")
        full = urljoin(base_url, href)
        if full not in links:
            links.append(full)
    return links


def fetch_text(url: str, timeout: float = 20.0) -> str:
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "tatemono-map/1.0"})
    r.raise_for_status()
    return r.text


def run(url: str, db_path: str, max_items: int = 200) -> int:
    conn = connect(db_path)
    fetched_at = datetime.now(timezone.utc).isoformat()

    smartlink_html = fetch_text(url)
    insert_raw_source(conn, "ulucks", "smartlink", url, smartlink_html)
    links = collect_smartview_links(smartlink_html, url)
    if not links:
        if re.search(r"flash|error", smartlink_html, re.IGNORECASE):
            raise RuntimeError("smartlink error page and no smartview links found")
        raise RuntimeError("no smartview links found")

    count = 0
    for link in links[:max_items]:
        html = fetch_text(link)
        insert_raw_source(conn, "ulucks", "smartview", link, html)
        parsed = parse_smartview_html(html, fetched_at=fetched_at)
        upsert_listing(
            conn,
            ListingRecord(
                name=parsed.name,
                address=parsed.address,
                rent_yen=parsed.rent_yen,
                area_sqm=parsed.area_sqm,
                layout=parsed.layout,
                updated_at=parsed.updated_at,
                source_kind="ulucks_smartview",
                source_url=link,
            ),
        )
        count += 1
    conn.close()
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--db-path", default="data/tatemono_map.sqlite3")
    parser.add_argument("--max-items", type=int, default=200)
    args = parser.parse_args()
    n = run(args.url, args.db_path, args.max_items)
    print(f"ingested listings: {n}")


if __name__ == "__main__":
    main()
