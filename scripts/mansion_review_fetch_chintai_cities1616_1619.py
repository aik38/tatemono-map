from __future__ import annotations

import argparse
import csv
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable
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
RETRY_COUNT = 2


@dataclass
class ChintaiRow:
    building_name: str
    room_no: str
    address: str
    layout: str
    area_sqm: float | None
    rent_man: float | None
    fee_man: float | None
    deposit_man: float | None
    key_money_man: float | None
    built: str
    floors: str
    access: str
    detail_url: str
    scraped_at: str
    city_id: int
    city_page: str


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def get(url: str, *, retries: int = RETRY_COUNT, sleep_sec: float = 0.0) -> str:
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = SESSION.get(url, timeout=30)
            r.raise_for_status()
            r.encoding = r.apparent_encoding
            return r.text
        except requests.RequestException as err:  # noqa: PERF203
            last_err = err
            if attempt >= retries:
                break
            if sleep_sec > 0:
                time.sleep(sleep_sec)
    assert last_err is not None
    raise last_err


def pick_text(el) -> str:
    if not el:
        return ""
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


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


def _find_value_by_label(text: str, labels: list[str]) -> str:
    for label in labels:
        m = re.search(fr"{label}\s*[:：]\s*([^\n\r]+)", text)
        if m:
            return m.group(1).strip()
    return ""


def _normalize_man(value: str) -> float | None:
    v = value.strip()
    if not v or v in {"-", "ー", "—", "なし", "無", "相談"}:
        return None

    m_man = re.search(r"(\d+(?:\.\d+)?)\s*万", v)
    if m_man:
        return float(m_man.group(1))

    m_yen = re.search(r"([\d,]+)\s*円", v)
    if m_yen:
        return round(float(m_yen.group(1).replace(",", "")) / 10000.0, 4)

    m_num = re.search(r"(\d+(?:\.\d+)?)", v)
    if m_num:
        return float(m_num.group(1))

    return None


def _extract_numeric_sqm(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m2|m²|㎡)", text)
    if m:
        return float(m.group(1))
    return None


def _split_building_and_room(raw_name: str) -> tuple[str, str]:
    name = re.sub(r"\s+", " ", raw_name).strip()
    if not name:
        return "", ""

    m = re.search(r"(\d{1,4})\s*号室", name)
    if not m:
        m = re.search(r"(\d{1,4})\s*(?:号|室)", name)
    if m:
        room_no = m.group(1)
        building_name = (name[: m.start()] + " " + name[m.end() :]).strip()
        building_name = re.sub(r"\s+", " ", building_name)
        return building_name, room_no

    trailing = re.search(r"^(.*\S)\s+(\d{1,4})$", name)
    if trailing:
        prefix = trailing.group(1)
        if not re.search(r"No\.\s*$", prefix, re.IGNORECASE):
            return prefix.strip(), trailing.group(2)

    return name, ""


def _extract_name(soup: BeautifulSoup) -> str:
    for sel in ["h1", "h2", ".property-name", ".bukkenName", ".mansionName", "title"]:
        el = soup.select_one(sel)
        txt = pick_text(el)
        if txt:
            txt = re.sub(r"\s*[|｜].*$", "", txt).strip()
            if txt:
                return txt
    return ""


def _extract_detail_fields(detail_html: str) -> dict[str, str | float | None]:
    soup = BeautifulSoup(detail_html, "lxml")
    text = pick_text(soup)
    text_lines = soup.get_text("\n", strip=True)

    raw_name = _extract_name(soup)
    building_name, room_no = _split_building_and_room(raw_name)

    address = _find_value_by_label(text_lines, ["住所", "所在地"])
    if not address:
        m_addr = re.search(r"(福岡県\s*北九州市[^\s、。,]+(?:[\d丁目番地\-－ー\s]+)?)", text)
        address = m_addr.group(1).strip() if m_addr else ""

    layout = _find_value_by_label(text_lines, ["間取り", "タイプ"])
    if not layout:
        m_layout = re.search(r"\b(\d+\s*[SLDKR]+)\b", text)
        layout = m_layout.group(1).replace(" ", "") if m_layout else ""

    area_sqm = _extract_numeric_sqm(_find_value_by_label(text_lines, ["専有面積", "面積", "占有面積"]) or text)

    rent_man = _normalize_man(_find_value_by_label(text_lines, ["賃料", "家賃"]))
    if rent_man is None:
        m = re.search(r"(\d+(?:\.\d+)?)\s*万円", text)
        if m:
            rent_man = float(m.group(1))

    fee_man = _normalize_man(_find_value_by_label(text_lines, ["管理費", "共益費", "管理費/共益費"]))
    deposit_man = _normalize_man(_find_value_by_label(text_lines, ["敷金"]))
    key_money_man = _normalize_man(_find_value_by_label(text_lines, ["礼金"]))

    built = _find_value_by_label(text_lines, ["築年月", "築年数"])
    if not built:
        m_built = re.search(r"(\d{4}年\d{1,2}月|築\d+年(?:\d+ヶ月)?)", text)
        built = m_built.group(1) if m_built else ""

    floors = _find_value_by_label(text_lines, ["階建", "建物階数", "所在階"])
    if not floors:
        m_floors = re.search(r"(地上\s*\d+\s*階(?:\s*地下\s*\d+\s*階)?)", text)
        floors = m_floors.group(1) if m_floors else ""

    access = _find_value_by_label(text_lines, ["交通", "アクセス"])
    if not access:
        m_access = re.search(r"([^\s]+駅\s*徒歩\s*\d+\s*分)", text)
        access = m_access.group(1) if m_access else ""

    return {
        "building_name": building_name,
        "room_no": room_no,
        "address": address,
        "layout": layout,
        "area_sqm": area_sqm,
        "rent_man": rent_man,
        "fee_man": fee_man,
        "deposit_man": deposit_man,
        "key_money_man": key_money_man,
        "built": built,
        "floors": floors,
        "access": access,
    }


def extract_rows_from_html(
    html: str,
    city_page: str,
    city_id: int,
    *,
    fetch_detail: Callable[[str], str] | None = None,
) -> tuple[list[ChintaiRow], int, int]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[ChintaiRow] = []

    detail_urls, a_count, regex_count = _extract_detail_links(soup, html)
    fetcher = fetch_detail or get

    for detail_url in detail_urls:
        try:
            detail_html = fetcher(detail_url)
        except requests.RequestException as err:
            print(f"[WARN] failed detail fetch: {detail_url} err={err}")
            continue

        detail = _extract_detail_fields(detail_html)
        if not detail["building_name"] and not detail["address"] and not detail["layout"]:
            print(f"[WARN] detail parse empty, skipped: {detail_url}")
            continue

        rows.append(
            ChintaiRow(
                building_name=str(detail["building_name"]),
                room_no=str(detail["room_no"]),
                address=str(detail["address"]),
                layout=str(detail["layout"]),
                area_sqm=detail["area_sqm"],
                rent_man=detail["rent_man"],
                fee_man=detail["fee_man"],
                deposit_man=detail["deposit_man"],
                key_money_man=detail["key_money_man"],
                built=str(detail["built"]),
                floors=str(detail["floors"]),
                access=str(detail["access"]),
                detail_url=detail_url,
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
    parser.add_argument("--sleep", type=float, default=SLEEP_SEC, help="リクエスト間隔（秒）")
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
                html = get(url, sleep_sec=args.sleep)
            except requests.HTTPError as e:
                if getattr(e.response, "status_code", None) == 404:
                    print(f"[STOP] city={city_id} page={page} 404 url={url}")
                    break
                raise

            rows, a_cnt, regex_cnt = extract_rows_from_html(
                html,
                city_page=url,
                city_id=city_id,
                fetch_detail=lambda detail_url: get(detail_url, sleep_sec=args.sleep),
            )
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
            time.sleep(args.sleep)

    fieldnames = list(asdict(all_rows[0]).keys()) if all_rows else [
        "building_name",
        "room_no",
        "address",
        "layout",
        "area_sqm",
        "rent_man",
        "fee_man",
        "deposit_man",
        "key_money_man",
        "built",
        "floors",
        "access",
        "detail_url",
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
