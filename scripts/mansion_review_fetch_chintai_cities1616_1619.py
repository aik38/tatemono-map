from __future__ import annotations

import argparse
import csv
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

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
DEFAULT_OUT = "mansion_review_chintai_1616_1619.csv"


@dataclass
class ChintaiRow:
    building_name: str
    room_no: str
    address: str
    access: str
    built: str
    floors: str
    units: str
    rent_man: float | None
    fee_yen: int | None
    deposit: str
    key_money: str
    area_sqm: float | None
    layout: str
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


def pick_text(el: Tag | None) -> str:
    if not el:
        return ""
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_header(text: str) -> str:
    txt = _normalize_space(text)
    txt = re.sub(r"\(.*?\)", "", txt)
    txt = txt.replace("（", "(").replace("）", ")")
    return txt


def _extract_numeric_sqm(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m2|m²|㎡)", text)
    if m:
        return float(m.group(1))
    return None


def _parse_rent_man(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*万", text)
    if m:
        return float(m.group(1))
    m = re.search(r"([\d,]+)\s*円", text)
    if m:
        return round(int(m.group(1).replace(",", "")) / 10000.0, 4)
    return None


def _parse_fee_yen(text: str) -> int | None:
    m = re.search(r"(?:管理費|共益費)?\s*[\(（]?\s*([\d,]+)\s*円", text)
    if m:
        return int(m.group(1).replace(",", ""))
    if "なし" in text or "-" in text or "ー" in text:
        return 0
    return None


def _split_building_and_room(raw_name: str) -> tuple[str, str]:
    name = _normalize_space(raw_name)
    if not name:
        return "", ""

    m = re.search(r"(\d{1,4})\s*号室", name)
    if m:
        room_no = m.group(1)
        building_name = (name[: m.start()] + " " + name[m.end() :]).strip()
        return _normalize_space(building_name), room_no

    trailing = re.search(r"^(.*\S)\s+(\d{1,4})$", name)
    if trailing:
        prefix = trailing.group(1)
        if not re.search(r"No\.\s*$", prefix, re.IGNORECASE):
            return prefix.strip(), trailing.group(2)

    return name, ""


def _extract_kv_pairs(container: Tag) -> dict[str, str]:
    pairs: dict[str, str] = {}

    for dt in container.select("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            pairs[_normalize_header(pick_text(dt))] = pick_text(dd)

    for tr in container.select("tr"):
        th = tr.find("th")
        td = tr.find("td")
        if th and td:
            pairs[_normalize_header(pick_text(th))] = pick_text(td)

    text = container.get_text("\n", strip=True)
    for line in text.splitlines():
        m = re.match(r"^([^:：]{1,20})\s*[:：]\s*(.+)$", line.strip())
        if m:
            pairs[_normalize_header(m.group(1))] = _normalize_space(m.group(2))

    return pairs


def _pick_value(pairs: dict[str, str], *labels: str) -> str:
    for label in labels:
        for key, value in pairs.items():
            if label in key and value:
                return value
    return ""


def _extract_building_name(container: Tag) -> str:
    for sel in ["h1", "h2", "h3", ".property-name", ".bukkenName", ".mansionName"]:
        el = container.select_one(sel)
        txt = pick_text(el)
        if txt:
            txt = re.sub(r"\s*[|｜].*$", "", txt).strip()
            return _split_building_and_room(txt)[0]
    return ""


def _parse_table_rows(table: Tag, building: dict[str, str], city_id: int, page_url: str) -> list[ChintaiRow]:
    rows: list[ChintaiRow] = []

    header_cells = table.select("thead tr th")
    if not header_cells:
        first_row = table.select_one("tr")
        if first_row:
            header_cells = first_row.find_all(["th", "td"])
    headers = [_normalize_header(pick_text(c)) for c in header_cells]
    header_map = {h: i for i, h in enumerate(headers) if h}

    body_rows = table.select("tbody tr")
    if not body_rows:
        body_rows = table.select("tr")
        if body_rows and header_cells:
            body_rows = body_rows[1:]

    for tr in body_rows:
        tds = tr.find_all("td")
        if not tds:
            continue
        texts = [pick_text(td) for td in tds]

        def get_by(*keys: str) -> str:
            for key in keys:
                for header, idx in header_map.items():
                    if key in header and idx < len(texts):
                        return texts[idx]
            return ""

        rent_text = get_by("賃料", "家賃") or " ".join(texts)
        layout = get_by("間取り", "タイプ")
        area_text = get_by("専有面積", "面積")
        deposit = get_by("敷金")
        key_money = get_by("礼金")
        room_no = get_by("部屋", "号室")

        if not layout:
            m_layout = re.search(r"\b(\d+\s*[SLDKR]+)\b", " ".join(texts))
            layout = m_layout.group(1).replace(" ", "") if m_layout else ""

        detail_url = ""
        for a in tr.select('a[href*="/chintai/"]'):
            href = (a.get("href") or "").strip()
            if re.search(r"/chintai/\d+", href):
                detail_url = urljoin(BASE, href)
                break

        rows.append(
            ChintaiRow(
                building_name=building["building_name"],
                room_no=room_no,
                address=building["address"],
                access=building["access"],
                built=building["built"],
                floors=building["floors"],
                units=building["units"],
                rent_man=_parse_rent_man(rent_text),
                fee_yen=_parse_fee_yen(rent_text),
                deposit=deposit,
                key_money=key_money,
                area_sqm=_extract_numeric_sqm(area_text),
                layout=layout,
                detail_url=detail_url,
                scraped_at=now_iso(),
                city_id=city_id,
                city_page=page_url,
            )
        )

    return rows


def extract_rows_from_city_html(html: str, city_page: str, city_id: int) -> list[ChintaiRow]:
    soup = BeautifulSoup(html, "lxml")
    rows: list[ChintaiRow] = []

    tables = soup.select("table")
    for table in tables:
        table_text = pick_text(table)
        if "賃料" not in table_text and "間取り" not in table_text:
            continue

        container = table
        while container.parent and isinstance(container.parent, Tag):
            parent = container.parent
            ptxt = pick_text(parent)
            if "住所" in ptxt and ("築" in ptxt or "交通" in ptxt):
                container = parent
                break
            container = parent

        pairs = _extract_kv_pairs(container if isinstance(container, Tag) else table)
        building_name = _extract_building_name(container if isinstance(container, Tag) else table)
        building = {
            "building_name": building_name,
            "address": _pick_value(pairs, "住所", "所在地"),
            "access": _pick_value(pairs, "交通", "アクセス"),
            "built": _pick_value(pairs, "築年月", "築年数"),
            "floors": _pick_value(pairs, "階建", "建物階数"),
            "units": _pick_value(pairs, "総戸数", "戸数"),
        }

        table_rows = _parse_table_rows(table, building, city_id, city_page)
        if table_rows:
            rows.extend(table_rows)

    dedup: dict[tuple[str, str, str], ChintaiRow] = {}
    for row in rows:
        key = (row.building_name, row.room_no, row.detail_url)
        dedup[key] = row

    return list(dedup.values())


def extract_building_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    for a in soup.select("a"):
        text = pick_text(a)
        href = (a.get("href") or "").strip()
        if "全" in text and "件を表示する" in text and href:
            links.append(urljoin(BASE, href))
    return list(dict.fromkeys(links))


def city_page_url(city_id: int, page: int) -> str:
    if page <= 1:
        return f"{BASE}/chintai/city/{city_id}.html"
    return f"{BASE}/chintai/city/{city_id}_{page}.html"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="抽出件数の詳細ログを表示")
    parser.add_argument("--sleep", type=float, default=SLEEP_SEC, help="リクエスト間隔（秒）")
    parser.add_argument("--max-pages", type=int, default=0, help="都市ページの最大巡回数（0で無制限）")
    parser.add_argument("--out", default=DEFAULT_OUT, help="出力CSVパス")
    parser.add_argument(
        "--mode",
        choices=["city", "building"],
        default="city",
        help="city: 市区ページのみ / building: 『全xx件を表示する』リンクも巡回",
    )
    return parser


def _fill_counts(rows: list[ChintaiRow]) -> tuple[int, int, int]:
    return (
        sum(1 for r in rows if r.address),
        sum(1 for r in rows if r.layout),
        sum(1 for r in rows if r.built),
    )


def _fieldnames() -> list[str]:
    return [
        "building_name",
        "room_no",
        "address",
        "access",
        "built",
        "floors",
        "units",
        "rent_man",
        "fee_yen",
        "deposit",
        "key_money",
        "area_sqm",
        "layout",
        "detail_url",
        "scraped_at",
        "city_id",
        "city_page",
    ]


def main() -> None:
    args = _build_arg_parser().parse_args()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pages_total = 0
    all_rows = 0

    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_fieldnames())
        writer.writeheader()
        f.flush()

        for city_id in CITY_IDS:
            page = 1
            while True:
                if args.max_pages and page > args.max_pages:
                    print(f"[STOP] city={city_id} reached max-pages={args.max_pages}")
                    break

                url = city_page_url(city_id, page)
                try:
                    html = get(url, sleep_sec=args.sleep)
                except requests.HTTPError as e:
                    if getattr(e.response, "status_code", None) == 404:
                        print(f"[STOP] city={city_id} page={page} 404 url={url}")
                        break
                    raise

                page_rows = extract_rows_from_city_html(html, city_page=url, city_id=city_id)

                if args.mode == "building":
                    for b_url in extract_building_links(html):
                        try:
                            b_html = get(b_url, sleep_sec=args.sleep)
                        except requests.RequestException as err:
                            print(f"[WARN] failed building fetch: {b_url} err={err}")
                            continue
                        b_rows = extract_rows_from_city_html(b_html, city_page=b_url, city_id=city_id)
                        page_rows.extend(b_rows)
                        time.sleep(args.sleep)

                dedup: dict[tuple[str, str, str, str], ChintaiRow] = {}
                for row in page_rows:
                    key = (row.building_name, row.room_no, row.layout, row.city_page)
                    dedup[key] = row
                page_rows = list(dedup.values())

                pages_total += 1
                all_rows += len(page_rows)

                for row in page_rows:
                    writer.writerow(asdict(row))
                f.flush()

                addr_filled, layout_filled, built_filled = _fill_counts(page_rows)
                print(f"[OK] city={city_id} page={page} rows+={len(page_rows)} total={all_rows} url={url}")
                if args.debug:
                    print(
                        f"[DEBUG] city={city_id} page={page} "
                        f"fill address={addr_filled}/{len(page_rows)} "
                        f"layout={layout_filled}/{len(page_rows)} built={built_filled}/{len(page_rows)}"
                    )

                if not page_rows and page > 1:
                    break

                page += 1
                time.sleep(args.sleep)

    print(f"[DONE] pages_total={pages_total} rows={all_rows} -> {out_path}")


if __name__ == "__main__":
    main()
