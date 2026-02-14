# scripts/mansion_review_fetch_mansion_cities1616_1619.py
from __future__ import annotations

import csv
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.mansion-review.jp"
START_URL = "https://www.mansion-review.jp/mansion/?city%5B%5D=1616&city%5B%5D=1619&search_x=1"

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

SLEEP_SEC = 0.8  # 連打しない（礼儀）

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

def find_next_url(soup: BeautifulSoup, current_url: str) -> str | None:
    # 「次へ」ボタン
    a = soup.find("a", string=re.compile(r"^\s*次へ\s*$"))
    if a and a.get("href"):
        href = a["href"]
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            return urljoin(BASE, href)

    # rel="next"
    a = soup.find("a", attrs={"rel": "next"})
    if a and a.get("href"):
        href = a["href"]
        if href.startswith("http"):
            return href
        if href.startswith("/"):
            return urljoin(BASE, href)

    return None

@dataclass
class MansionRow:
    scraped_at: str
    source_url: str
    detail_url: str
    mansion_name: str
    address: str
    access: str
    built: str
    floors: str
    units: str
    reviews: str

def parse_page(html: str, source_url: str) -> tuple[list[MansionRow], str | None]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[MansionRow] = []

    # 詳細ページっぽいリンクを起点に拾う（/mansion/数字...）
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        if not href:
            continue
        if not re.search(r"^/mansion/\d+", href):
            continue

        # 親を辿って“カード”を掴む
        card = a
        for _ in range(6):
            if card and getattr(card, "name", None) in ("li", "div", "article", "section"):
                txt = pick_text(card)
                if len(txt) > 30:
                    break
            card = card.parent

        detail_url = urljoin(BASE, href)
        name = pick_text(a)

        card_text = pick_text(card)

        # 住所（福岡県北九州市...）
        m_addr = re.search(r"(福岡県\s*北九州市.*?)(?:\s|$)", card_text)
        address = (m_addr.group(1).strip() if m_addr else "")

        # 交通（駅 徒歩X分）
        m_access = re.search(r"([^\s]+駅\s*徒歩\s*\d+\s*分)", card_text)
        access = (m_access.group(1) if m_access else "")

        # 築年（YYYY年M月）
        m_built = re.search(r"(\d{4}年\d{1,2}月)", card_text)
        built = (m_built.group(1) if m_built else "")

        # 階建て（地上XX階 地下X階）
        m_floors = re.search(r"(地上\s*\d+\s*階(?:\s*地下\s*\d+\s*階)?)", card_text)
        floors = (m_floors.group(1) if m_floors else "")

        # 総戸数
        m_units = re.search(r"(?:総戸数|戸数)\s*[:：]?\s*(\d+\s*戸)", card_text)
        units = (m_units.group(1) if m_units else "")

        # 口コミ数
        m_reviews = re.search(r"(?:口コミ数|口コミ)\s*[:：]?\s*(\d+)", card_text)
        reviews = (m_reviews.group(1) if m_reviews else "")

        if name and detail_url:
            rows.append(MansionRow(
                scraped_at=now_iso(),
                source_url=source_url,
                detail_url=detail_url,
                mansion_name=name,
                address=address,
                access=access,
                built=built,
                floors=floors,
                units=units,
                reviews=reviews,
            ))

    # detail_urlで重複排除
    uniq: dict[str, MansionRow] = {}
    for r in rows:
        uniq[r.detail_url] = r

    next_url = find_next_url(soup, source_url)
    return list(uniq.values()), next_url

def main() -> None:
    out_csv = "mansion_review_mansions_1616_1619.csv"

    url = START_URL
    pages = 0
    all_rows: list[MansionRow] = []
    seen: set[str] = set()

    while url and url not in seen:
        seen.add(url)
        pages += 1

        html = get(url)
        rows, next_url = parse_page(html, url)
        all_rows.extend(rows)

        print(f"[OK] page={pages} rows+={len(rows)} total={len(all_rows)} url={url}")

        url = next_url
        time.sleep(SLEEP_SEC)

    fieldnames = list(asdict(all_rows[0]).keys()) if all_rows else [
        "scraped_at","source_url","detail_url","mansion_name","address","access","built","floors","units","reviews"
    ]

    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in all_rows:
            w.writerow(asdict(r))

    print(f"[DONE] pages={pages} rows={len(all_rows)} -> {out_csv}")

if __name__ == "__main__":
    main()
