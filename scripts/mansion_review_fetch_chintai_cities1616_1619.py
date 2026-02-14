from __future__ import annotations

import argparse
import csv
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.mansion-review.jp"

# 1616=門司区, 1619=小倉北区
CITY_IDS = [1616, 1619]

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.8",
}

SESSION = requests.Session()
SESSION.headers.update(UA)

SLEEP_SEC = 0.8


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def get(url: str) -> str:
    r = SESSION.get(url, timeout=30)
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    return r.text


def pick_text(el) -> str:
    if not el:
        return ""
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


@dataclass
class ChintaiRow:
    mansion_name: str
    address: str
    detail_url: str
    built: str
    floors: str
    units: str
    reviews: str
    access: str
    scraped_at: str
    city_id: int
    city_page: str


def _guess_name(a, card, card_text: str, detail_url: str) -> str:
    name = pick_text(a)
    if name:
        return name

    for k in ("title", "aria-label"):
        v = (a.get(k) or "").strip()
        if v:
            return v

    img = a.find("img")
    if img:
        v = (img.get("alt") or "").strip()
        if v:
            return v

    if card:
        cand = card.select_one(
            "h1, h2, h3, "
            ".mansionName, .mansion-name, .mansion_name, "
            ".bukkenName, .bukken-name, .bukken_name, "
            ".propertyName, .property-name, .property_name, "
            ".name, .title"
        )
        name = pick_text(cand)
        if name:
            return name

    if card_text:
        head = re.split(r"(福岡県|住所|交通|築|地上|総戸数|口コミ)", card_text)[0]
        head = head.strip(" 　\t\r\n-–—|｜")
        if head and len(head) <= 80:
            return head

    return detail_url


def _extract_detail_links(soup: BeautifulSoup, html: str) -> tuple[list[str], int, int]:
    detail_urls: list[str] = []

    a_links = 0
    for a in soup.select('a[href*="/chintai/"]'):
        href = (a.get("href") or "").strip()
        if not re.search(r"/chintai/\d+", href):
            continue
        detail_urls.append(urljoin(BASE, href))
        a_links += 1

    regex_links = 0
    if a_links == 0:
        for path in re.findall(r"/chintai/\d+", html):
            detail_urls.append(urljoin(BASE, path))
            regex_links += 1

    uniq_urls = list(dict.fromkeys(detail_urls))
    return uniq_urls, a_links, regex_links


def extract_rows_from_html(
    html: str,
    city_page: str,
    city_id: int,
) -> tuple[list[ChintaiRow], int, int]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[ChintaiRow] = []

    detail_urls, a_count, regex_count = _extract_detail_links(soup, html)

    anchors = soup.select('a[href*="/chintai/"]')

    for detail_url in detail_urls:
        path = re.sub(r"^https?://[^/]+", "", detail_url)
        a = None
        for anchor in anchors:
            href = (anchor.get("href") or "").strip()
            if not href:
                continue
            abs_href = urljoin(BASE, href)
            if detail_url == abs_href or re.search(r"/chintai/\d+", href) and path in href:
                a = anchor
                break

        if not a:
            card = soup
            card_text = pick_text(soup)
            name = detail_url
        else:
            card = a
            for _ in range(12):
                parent = getattr(card, "parent", None)
                if not parent:
                    break
                card = parent
                if len(pick_text(card)) >= 40:
                    break

            card_text = pick_text(card)
            name = _guess_name(a, card, card_text, detail_url)

            if name == detail_url:
                heading = card.find(["h1", "h2", "h3", "h4"])
                heading_text = pick_text(heading)
                if heading_text:
                    name = heading_text

        m_addr = re.search(r"(福岡県\s*北九州市.*?)(?:\s|$)", card_text)
        address = m_addr.group(1).strip() if m_addr else ""

        m_access = re.search(r"([^\s]+駅\s*徒歩\s*\d+\s*分)", card_text)
        access = m_access.group(1) if m_access else ""

        m_built = re.search(r"(\d{4}年\d{1,2}月)", card_text)
        built = m_built.group(1) if m_built else ""

        m_floors = re.search(r"(地上\s*\d+\s*階(?:\s*地下\s*\d+\s*階)?)", card_text)
        floors = m_floors.group(1) if m_floors else ""

        m_units = re.search(r"(?:総戸数|戸数)\s*[:：]?\s*(\d+\s*戸)", card_text)
        units = m_units.group(1) if m_units else ""

        m_reviews = re.search(r"(?:口コミ数|口コミ)\s*[:：]?\s*(\d+)", card_text)
        reviews = m_reviews.group(1) if m_reviews else ""

        rows.append(
            ChintaiRow(
                mansion_name=name,
                address=address,
                detail_url=detail_url,
                built=built,
                floors=floors,
                units=units,
                reviews=reviews,
                access=access,
                scraped_at=now_iso(),
                city_id=city_id,
                city_page=city_page,
            )
        )

    uniq: dict[str, ChintaiRow] = {}
    for row in rows:
        uniq[row.detail_url] = row

    return list(uniq.values()), a_count, regex_count


def city_page_url(city_id: int, page: int) -> str:
    if page <= 1:
        return f"{BASE}/chintai/city/{city_id}.html"
    return f"{BASE}/chintai/city/{city_id}_{page}.html"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="抽出件数の詳細ログを表示")
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    out_csv = "mansion_review_chintai_1616_1619.csv"

    all_rows: list[ChintaiRow] = []
    pages_total = 0

    for city_id in CITY_IDS:
        page = 1
        while True:
            url = city_page_url(city_id, page)
            try:
                html = get(url)
            except requests.HTTPError as e:
                if getattr(e.response, "status_code", None) == 404:
                    print(f"[STOP] city={city_id} page={page} 404 url={url}")
                    break
                raise

            rows, a_cnt, regex_cnt = extract_rows_from_html(html, city_page=url, city_id=city_id)
            link_cnt = a_cnt + regex_cnt

            pages_total += 1
            all_rows.extend(rows)

            print(
                f"[OK] city={city_id} page={page} "
                f"rows+={len(rows)} total={len(all_rows)} "
                f"detail_links={link_cnt} url={url}"
            )

            if args.debug:
                print(
                    f"[DEBUG] city={city_id} page={page} "
                    f"rows={len(rows)} a_extract={a_cnt} regex_extract={regex_cnt}"
                )

            if link_cnt == 0:
                break
            if len(rows) == 0 and page > 1:
                break

            page += 1
            time.sleep(SLEEP_SEC)

    fieldnames = list(asdict(all_rows[0]).keys()) if all_rows else [
        "mansion_name",
        "address",
        "detail_url",
        "built",
        "floors",
        "units",
        "reviews",
        "access",
        "scraped_at",
        "city_id",
        "city_page",
    ]

    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in all_rows:
            w.writerow(asdict(row))

    print(f"[DONE] pages_total={pages_total} rows={len(all_rows)} -> {out_csv}")


if __name__ == "__main__":
    main()
