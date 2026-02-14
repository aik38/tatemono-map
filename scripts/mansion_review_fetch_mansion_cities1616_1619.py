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

# 1616=門司区, 1619=小倉北区（あなたの確認済みURL規則に合わせる）
CITY_PAGES = [
    (1616, "門司区"),
    (1619, "小倉北区"),
]

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

SLEEP_SEC = 0.8  # 礼儀（連打しない）

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
class MansionRow:
    scraped_at: str
    city_id: int
    city_name: str
    source_url: str
    detail_url: str
    mansion_name: str
    address: str
    access: str
    built: str
    floors: str
    units: str
    reviews: str

def extract_rows_from_html(html: str, source_url: str, city_id: int, city_name: str) -> list[MansionRow]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[MansionRow] = []

    # 一覧内の詳細リンク（/mansion/数字...）を拾う
    for a in soup.select('a[href^="/mansion/"]'):
        href = a.get("href") or ""
        if not re.search(r"^/mansion/\d+", href):
            continue

        detail_url = urljoin(BASE, href)
        name = pick_text(a)
        if not name:
            continue

        # 親を辿ってカード相当の塊を掴む（テキストが一定以上ある要素）
        card = a
        for _ in range(8):
            parent = getattr(card, "parent", None)
            if not parent:
                break
            card = parent
            txt = pick_text(card)
            if len(txt) >= 40:
                break

        card_text = pick_text(card)

        # 住所（福岡県北九州市...）
        m_addr = re.search(r"(福岡県\s*北九州市.*?)(?:\s|$)", card_text)
        address = m_addr.group(1).strip() if m_addr else ""

        # 交通（駅 徒歩X分）
        m_access = re.search(r"([^\s]+駅\s*徒歩\s*\d+\s*分)", card_text)
        access = m_access.group(1) if m_access else ""

        # 築年月（YYYY年M月）
        m_built = re.search(r"(\d{4}年\d{1,2}月)", card_text)
        built = m_built.group(1) if m_built else ""

        # 階建て（地上XX階 地下X階）
        m_floors = re.search(r"(地上\s*\d+\s*階(?:\s*地下\s*\d+\s*階)?)", card_text)
        floors = m_floors.group(1) if m_floors else ""

        # 総戸数（○戸）
        m_units = re.search(r"(?:総戸数|戸数)\s*[:：]?\s*(\d+\s*戸)", card_text)
        units = m_units.group(1) if m_units else ""

        # 口コミ数（数値だけ拾う）
        m_reviews = re.search(r"(?:口コミ数|口コミ)\s*[:：]?\s*(\d+)", card_text)
        reviews = m_reviews.group(1) if m_reviews else ""

        rows.append(MansionRow(
            scraped_at=now_iso(),
            city_id=city_id,
            city_name=city_name,
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
    return list(uniq.values())

def city_page_url(city_id: int, page: int) -> str:
    # 1ページ目: /mansion/city/1616.html
    # 2ページ目: /mansion/city/1616_2.html
    if page <= 1:
        return f"{BASE}/mansion/city/{city_id}.html"
    return f"{BASE}/mansion/city/{city_id}_{page}.html"

def main() -> None:
    out_csv = "mansion_review_mansions_1616_1619.csv"

    all_rows: list[MansionRow] = []
    pages_total = 0

    for city_id, city_name in CITY_PAGES:
        page = 1
        while True:
            url = city_page_url(city_id, page)
            html = get(url)
            rows = extract_rows_from_html(html, url, city_id, city_name)

            pages_total += 1
            all_rows.extend(rows)
            print(f"[OK] city={city_id} page={page} rows+={len(rows)} total={len(all_rows)} url={url}")

            # そのページで0件なら、そこが終端（以降の _{n} も無い/空のはず）
            if len(rows) == 0:
                break

            page += 1
            time.sleep(SLEEP_SEC)

    fieldnames = list(asdict(all_rows[0]).keys()) if all_rows else [
        "scraped_at","city_id","city_name","source_url","detail_url","mansion_name",
        "address","access","built","floors","units","reviews"
    ]

    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in all_rows:
            w.writerow(asdict(r))

    print(f"[DONE] pages_total={pages_total} rows={len(all_rows)} -> {out_csv}")

if __name__ == "__main__":
    main()
