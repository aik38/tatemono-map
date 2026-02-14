# scripts/mansion_review_fetch_city400001.py
from __future__ import annotations

import csv
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup

BASE = "https://www.mansion-review.jp"

START_URL = "https://www.mansion-review.jp/chintai/city/400001.html?condition=on&sub_city%5B%5D=1616&sub_city%5B%5D=1619&homes_cond_monthmoneyroom_min=0&homes_cond_monthmoneyroom_max=99999999&homes_cond_housearea_min=0&homes_cond_housearea_max=9999&search=%E6%A4%9C%E7%B4%A2%E3%81%99%E3%82%8B"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": UA,
        "Accept-Language": "ja,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
)

ROOM_SUFFIX_RE = re.compile(r"\s*[0-9A-Za-z\-]+(?:号室)?$")

@dataclass
class VacancyRow:
    scraped_at: str
    source_url: str
    detail_url: str
    building_name_raw: str
    building_name_norm: str
    rent_text: str
    deposit_text: str
    key_money_text: str
    area_sqm_text: str
    layout_text: str
    floor_text: str
    direction_text: str

def strip_fragment(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, p.query, ""))

def fetch(url: str, *, sleep_sec: float = 0.8, timeout: int = 30) -> str:
    time.sleep(sleep_sec)
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text

def normalize_building_name(name: str) -> str:
    n = re.sub(r"\s+", " ", name).strip()
    n = ROOM_SUFFIX_RE.sub("", n)
    return n.strip()

def parse_vacancy_rows(html: str, page_url: str) -> list[VacancyRow]:
    soup = BeautifulSoup(html, "html.parser")
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    out: list[VacancyRow] = []
    for tbody in soup.select("tbody.recommend_row"):
        tr = tbody.find("tr")
        if not tr:
            continue

        tds = tr.find_all("td")
        if len(tds) < 8:
            continue

        a = tr.find("a", href=True)
        if not a:
            continue

        detail_url = a["href"]
        if detail_url.startswith("/"):
            detail_url = urljoin(BASE, detail_url)

        name_raw = a.get_text(strip=True)
        name_norm = normalize_building_name(name_raw)

        # 列順は一覧仕様に依存（必要ならログで調整）
        rent_text      = tds[2].get_text(" ", strip=True)
        deposit_text   = tds[3].get_text(" ", strip=True)
        key_money_text = tds[4].get_text(" ", strip=True)
        area_sqm_text  = tds[5].get_text(" ", strip=True)
        layout_text    = tds[6].get_text(" ", strip=True)
        floor_text     = tds[7].get_text(" ", strip=True)
        direction_text = tds[8].get_text(" ", strip=True) if len(tds) > 8 else ""

        out.append(
            VacancyRow(
                scraped_at=now,
                source_url=page_url,
                detail_url=detail_url,
                building_name_raw=name_raw,
                building_name_norm=name_norm,
                rent_text=rent_text,
                deposit_text=deposit_text,
                key_money_text=key_money_text,
                area_sqm_text=area_sqm_text,
                layout_text=layout_text,
                floor_text=floor_text,
                direction_text=direction_text,
            )
        )
    return out

def discover_pagination_urls(html: str, current_url: str) -> list[str]:
    """
    ページ内のページングリンクを拾う。
    条件（query）が付いたままのリンクを優先。
    """
    soup = BeautifulSoup(html, "html.parser")
    urls = set([strip_fragment(current_url)])

    for a in soup.select("a[href]"):
        href = a.get("href")
        if not href:
            continue
        u = urljoin(BASE, href)
        u = strip_fragment(u)
        # 同じ city/400001.html かつ condition=on 系のものだけ拾う（広げすぎ防止）
        if "/chintai/city/400001.html" in u and "condition=on" in u:
            urls.add(u)

    return sorted(urls)

def main():
    start = strip_fragment(START_URL)
    html0 = fetch(start)

    page_urls = discover_pagination_urls(html0, start)

    all_rows: list[VacancyRow] = []
    seen = set()

    for pu in page_urls:
        html = html0 if pu == start else fetch(pu)
        rows = parse_vacancy_rows(html, pu)
        for r in rows:
            key = (r.detail_url, r.rent_text, r.area_sqm_text, r.floor_text)
            if key in seen:
                continue
            seen.add(key)
            all_rows.append(r)

    if not all_rows:
        raise SystemExit("No rows extracted. The page may require different selectors or login/cookies.")

    out_path = "mansion_review_vacancies_400001_moji_kokurakita.csv"
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(all_rows[0]).keys()))
        w.writeheader()
        for r in all_rows:
            w.writerow(asdict(r))

    print(f"[OK] pages={len(page_urls)} rows={len(all_rows)} -> {out_path}")

if __name__ == "__main__":
    main()
