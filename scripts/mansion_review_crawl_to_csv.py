from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from selectolax.parser import HTMLParser, Node

BASE_URL = "https://www.mansion-review.jp"
DEFAULT_OUT = Path("tmp/manual/outputs/mansion_review")
DEFAULT_CACHE = Path("tmp/manual/cache/mansion_review")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

CITY_MAP = {
    "1616": "門司区",
    "1619": "小倉北区",
}

LIST_COLUMNS = (
    "kind",
    "city_id",
    "ward",
    "city_page",
    "page_url",
    "detail_url",
    "building_name",
    "address",
    "access_text",
    "built_text",
    "building_floor_count_text",
    "total_units_text",
    "price_or_rent_text",
    "fee_text",
    "tsubo_unit_price_text",
    "deposit_text",
    "key_money_text",
    "area_text",
    "layout_text",
    "floor_text",
    "direction_text",
)

FACTS_COLUMNS = (
    "building_name",
    "address",
    "access_info",
    "built_text",
    "floor_count_text",
    "total_units",
    "evidence_id",
)

MASTER_COLUMNS = (
    "page",
    "category",
    "updated_at",
    "building_name",
    "room",
    "address",
    "rent_man",
    "fee_man",
    "floor",
    "layout",
    "area_sqm",
    "availability_raw",
    "built_raw",
    "age_years",
    "structure",
    "built_year_month",
    "built_age_years",
    "availability_date",
    "availability_flag_immediate",
    "structure_raw",
    "raw_block",
    "evidence_id",
)

CHINTAI_ORDER = ["賃料", "管理費", "敷金", "礼金", "専有面積", "間取り"]
MANSION_ORDER = ["価格", "㎡単価", "専有面積", "間取り", "所在階", "向き"]


@dataclass
class ListRow:
    kind: str
    city_id: str
    ward: str
    city_page: str
    page_url: str
    detail_url: str
    building_name: str
    address: str
    access_text: str
    built_text: str
    building_floor_count_text: str
    total_units_text: str
    price_or_rent_text: str
    fee_text: str
    tsubo_unit_price_text: str
    deposit_text: str
    key_money_text: str
    area_text: str
    layout_text: str
    floor_text: str
    direction_text: str


def normalize_space(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_csv_arg(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_city_page_url(kind: str, city_id: str, page: int) -> str:
    suffix = "" if page == 1 else f"_{page}"
    return f"{BASE_URL}/{kind}/city/{city_id}{suffix}.html"


def _city_page_pattern(kind: str, city_id: str) -> re.Pattern[str]:
    return re.compile(rf"/{re.escape(kind)}/city/{re.escape(city_id)}(?:_(\d+))?\.html(?:$|[?#])")


def parse_max_page(html: str, *, kind: str, city_id: str) -> int:
    tree = HTMLParser(html)
    pattern = _city_page_pattern(kind, city_id)
    max_page = 1
    for node in tree.css("a[href]"):
        href = normalize_space(node.attributes.get("href"))
        m = pattern.search(href)
        if m:
            max_page = max(max_page, int(m.group(1) or "1"))
    return max_page


def _extract_facts_map(card: Node) -> dict[str, str]:
    root = card.css_first(".property-detail-content_main")
    if root is None:
        return {}

    facts: dict[str, str] = {}
    for dl in root.css("dl"):
        dts = dl.css("dt")
        dds = dl.css("dd")
        for dt, dd in zip(dts, dds):
            key = normalize_space(dt.text(separator=" ")).replace("：", "").replace(":", "")
            val = normalize_space(dd.text(separator=" "))
            if key and val:
                facts[key] = val

    for row in root.css("tr"):
        th = row.css_first("th")
        td = row.css_first("td")
        if not th or not td:
            continue
        key = normalize_space(th.text(separator=" ")).replace("：", "").replace(":", "")
        val = normalize_space(td.text(separator=" "))
        if key and val:
            facts[key] = val

    return facts


def _fact(facts: dict[str, str], *labels: str) -> str:
    for label in labels:
        value = normalize_space(facts.get(label))
        if value:
            return value
    return ""


def _extract_detail_url(card: Node, page_url: str, kind: str) -> str:
    pattern = re.compile(rf"/(?:{re.escape(kind)})/\d+(?:/\d+)?(?:\.html)?(?:$|[?#])")
    for a in card.css("a[href]"):
        href = normalize_space(a.attributes.get("href"))
        if pattern.search(href):
            return urljoin(page_url, href)
    return ""


def _table_headers(table: Node) -> list[str]:
    ths = table.css("thead th") or table.css("tr.recommend_head th, tr.recommendHead th")
    return [normalize_space(th.text(separator=" ")).replace(" ", "") for th in ths]


def _row_columns(tr: Node, headers: list[str], order: list[str]) -> dict[str, str]:
    cells = [normalize_space(td.text(separator=" ")) for td in tr.css("td")]
    if not cells:
        return {}

    if headers:
        return {headers[i]: cells[i] for i in range(min(len(headers), len(cells)))}

    labeled: dict[str, str] = {}
    for i, td in enumerate(tr.css("td")):
        key = normalize_space(
            td.attributes.get("data-th")
            or td.attributes.get("data-title")
            or td.attributes.get("data-label")
        ).replace(" ", "")
        if key:
            labeled[key] = cells[i]
    if labeled:
        return labeled

    return {order[i]: cells[i] for i in range(min(len(order), len(cells)))}


def _row_cells(tr: Node) -> list[dict[str, str]]:
    cells: list[dict[str, str]] = []
    for td in tr.css("td"):
        text = normalize_space(td.text(separator=" "))
        label = normalize_space(
            td.attributes.get("data-th")
            or td.attributes.get("data-title")
            or td.attributes.get("data-label")
        ).replace(" ", "")
        classes = normalize_space(td.attributes.get("class"))
        cells.append({"text": text, "label": label, "class": classes})
    return cells


def _is_area_text(text: str) -> bool:
    return bool(re.search(r"\d+(?:\.\d+)?\s*(?:㎡|m²|m2)", text))


def _is_layout_text(text: str) -> bool:
    return bool(
        re.search(r"(?:\d+\s*(?:R|K|DK|LDK|SLDK)|ワンルーム|1R|1K|1DK|1LDK|2LDK|3LDK|4LDK)", text, re.IGNORECASE)
    )


def _is_floor_text(text: str) -> bool:
    return bool(re.search(r"(?:所在階|[Bb]?\d+\s*(?:階|F))", text))


def _is_direction_text(text: str) -> bool:
    t = normalize_space(text)
    if not t:
        return False
    if re.search(r"(北東|北西|南東|南西|東|西|南|北)(向き)?$", t):
        return True
    return "向き" in t and bool(re.search(r"(東|西|南|北)", t))


def _is_tsubo_text(text: str) -> bool:
    return "坪" in text and bool(re.search(r"(?:\d[\d,.]*\s*万?円?)", text))


def _is_money_text(text: str) -> bool:
    return bool(re.search(r"\d[\d,.]*(?:\.\d+)?\s*(?:万円|円)", text))


def _is_deposit_or_key_text(text: str) -> bool:
    t = normalize_space(text)
    if not t:
        return False
    if any(token in t for token in ("なし", "無", "-")):
        return True
    if re.search(r"\d+(?:\.\d+)?\s*(?:ヶ月|か月)", t):
        return True
    return bool(re.search(r"\d[\d,.]*\s*円", t)) and "万円" not in t


def _is_deco_cell(cell: dict[str, str], building_name: str) -> bool:
    text = cell["text"]
    label = cell["label"]
    classes = cell["class"]
    if not text:
        return True
    if "icon" in classes.lower():
        return True
    if text in {"新着", "リノベ", "リフォーム", "NEW"}:
        return True
    if "号室" in text:
        return True
    if building_name and normalize_space(building_name) == normalize_space(text):
        return True
    if not label and not _is_money_text(text) and not any(
        (
            _is_area_text(text),
            _is_layout_text(text),
            _is_floor_text(text),
            _is_direction_text(text),
            _is_tsubo_text(text),
            _is_deposit_or_key_text(text),
        )
    ):
        return True
    return False


def _extract_chintai_row(cols: dict[str, str], cells: list[dict[str, str]], building_name: str) -> dict[str, str]:
    rent = normalize_space(
        cols.get("賃料")
        or cols.get("賃料(管理費)")
        or cols.get("賃料（管理費）")
        or cols.get("賃料(管理費等)")
        or cols.get("賃料（管理費等）")
    )
    fee = normalize_space(cols.get("管理費") or cols.get("共益費"))
    if not fee and rent:
        m = re.search(r"[（(]\s*(?:管理費|共益費)[^0-9]*(\d[\d,]*(?:円|万円)?|無料|-)\s*[)）]", rent)
        if m:
            fee = normalize_space(m.group(1))
            rent = normalize_space(re.sub(r"\s*[（(].*[)）]\s*$", "", rent))

    deposit = normalize_space(cols.get("敷金") or cols.get("敷/礼"))
    key_money = normalize_space(cols.get("礼金"))
    if deposit and not key_money and "/" in deposit:
        parts = [normalize_space(p) for p in deposit.split("/", 1)]
        deposit = parts[0]
        key_money = parts[1] if len(parts) > 1 else ""

    area = normalize_space(cols.get("専有面積") or cols.get("面積"))
    layout = normalize_space(cols.get("間取り"))

    if rent and not _is_money_text(rent):
        rent = ""
    if fee and not (_is_money_text(fee) or fee in {"無料", "なし", "無", "-"}):
        fee = ""
    if deposit and not _is_deposit_or_key_text(deposit):
        deposit = ""
    if key_money and not _is_deposit_or_key_text(key_money):
        key_money = ""
    if area and not _is_area_text(area):
        area = ""
    if layout and not _is_layout_text(layout):
        layout = ""

    if not area or not layout:
        data_cells = [c for c in cells if not _is_deco_cell(c, building_name)]
        for cell in data_cells:
            text = cell["text"]
            label = cell["label"]
            if not rent and (_is_money_text(text) and not any(k in text for k in ("管理費", "共益費", "敷", "礼"))):
                rent = text
                continue
            if not fee and ("管理費" in label or "共益費" in label or "管理費" in text or "共益費" in text):
                fee = text
                continue
            if (
                not fee
                and rent
                and _is_money_text(text)
                and not _is_tsubo_text(text)
                and not any(k in text for k in ("敷", "礼"))
                and not _is_area_text(text)
            ):
                fee = text
                continue
            if not deposit and ("敷" in label or "敷" in text):
                deposit = text
                continue
            if not key_money and ("礼" in label or "礼" in text):
                key_money = text
                continue
            if not deposit and _is_deposit_or_key_text(text):
                deposit = text
                continue
            if not key_money and deposit and _is_deposit_or_key_text(text):
                key_money = text
                continue
            if not area and _is_area_text(text):
                area = text
                continue
            if not layout and _is_layout_text(text):
                layout = text
                continue

    return {
        "price_or_rent_text": rent,
        "fee_text": fee,
        "deposit_text": deposit,
        "key_money_text": key_money,
        "area_text": area,
        "layout_text": layout,
    }


def _extract_mansion_row(cols: dict[str, str], cells: list[dict[str, str]], building_name: str) -> dict[str, str]:
    price = normalize_space(cols.get("価格") or cols.get("販売価格"))
    area = normalize_space(cols.get("専有面積") or cols.get("面積"))
    layout = normalize_space(cols.get("間取り"))
    floor = normalize_space(cols.get("所在階") or cols.get("階"))
    direction = normalize_space(cols.get("向き") or cols.get("主要採光面"))

    if price and (not _is_money_text(price) or _is_tsubo_text(price)):
        price = ""
    if area and not _is_area_text(area):
        area = ""
    if layout and not _is_layout_text(layout):
        layout = ""
    if floor and not _is_floor_text(floor):
        floor = ""
    if direction and not _is_direction_text(direction):
        direction = ""
    if "万円台" in price or "無料会員" in price or "モザイク" in price:
        price = ""

    if not all((price, area, layout, floor, direction)):
        data_cells = [c for c in cells if not _is_deco_cell(c, building_name)]
        for cell in data_cells:
            text = cell["text"]
            label = cell["label"]
            if not area and ("面積" in label or _is_area_text(text)):
                area = text
                continue
            if not layout and ("間取り" in label or _is_layout_text(text)):
                layout = text
                continue
            if not floor and ("所在階" in label or _is_floor_text(text)):
                floor = text
                continue
            if not direction and _is_direction_text(text):
                direction = text
                continue
            if not price and (
                (("価格" in label or "販売価格" in label) and "万円台" not in text and "無料会員" not in text and "モザイク" not in text)
                or (
                    _is_money_text(text)
                    and not _is_tsubo_text(text)
                    and "万円台" not in text
                    and "無料会員" not in text
                    and "モザイク" not in text
                )
            ):
                price = text
                continue

    sqm_unit = _calc_sqm_unit_price_text(price, area)
    return {
        "price_or_rent_text": price,
        "tsubo_unit_price_text": sqm_unit,
        "area_text": area,
        "layout_text": layout,
        "floor_text": floor,
        "direction_text": direction,
    }


def parse_list_page(html: str, page_url: str, kind: str, city_id: str, page_no: int) -> tuple[list[ListRow], dict[str, int]]:
    tree = HTMLParser(html)
    cards = tree.css("li.property-detail-list-item, section.property-detail-list-item, article.property-detail-list-item")
    rows: list[ListRow] = []

    for card in cards:
        facts = _extract_facts_map(card)
        name_node = card.css_first("h1, h2, h3, .property-name, .mansionName")
        building_name = normalize_space(name_node.text(separator=" ") if name_node else "")
        detail_url = _extract_detail_url(card, page_url, kind)

        tables = card.css("table.recommendTable")
        if not tables:
            continue

        target_tables = tables
        if kind == "mansion":
            preferred = []
            for table in tables:
                title = normalize_space(" ".join(th.text(separator=" ") for th in table.css("tr.recommend_head th, tr.recommendHead th")))
                if "中古" in title and "販売情報" in title:
                    preferred.append(table)
            if preferred:
                target_tables = preferred

        for table in target_tables:
            for node in table.css("script, style, noscript, template"):
                node.decompose()
            headers = _table_headers(table)
            row_nodes = table.css("tbody.recommend_row tr")
            for tr in row_nodes:
                for node in tr.css("script, style, noscript, template"):
                    node.decompose()
                cells = _row_cells(tr)
                cols = _row_columns(tr, headers, CHINTAI_ORDER if kind == "chintai" else MANSION_ORDER)
                if not cols and not cells:
                    continue

                if kind == "chintai":
                    listing = _extract_chintai_row(cols, cells, building_name)
                    rows.append(
                        ListRow(
                            kind=kind,
                            city_id=city_id,
                            ward=CITY_MAP.get(city_id, ""),
                            city_page=f"{city_id}_{page_no}",
                            page_url=page_url,
                            detail_url=detail_url,
                            building_name=building_name,
                            address=_fact(facts, "住所", "所在地"),
                            access_text=_fact(facts, "交通", "アクセス"),
                            built_text=_fact(facts, "築年数", "築年月", "築"),
                            building_floor_count_text=_fact(facts, "階建て", "建物階数"),
                            total_units_text=_fact(facts, "総戸数"),
                            price_or_rent_text=listing["price_or_rent_text"],
                            fee_text=listing["fee_text"],
                            tsubo_unit_price_text="",
                            deposit_text=listing["deposit_text"],
                            key_money_text=listing["key_money_text"],
                            area_text=listing["area_text"],
                            layout_text=listing["layout_text"],
                            floor_text="",
                            direction_text="",
                        )
                    )
                else:
                    sale = _extract_mansion_row(cols, cells, building_name)
                    rows.append(
                        ListRow(
                            kind=kind,
                            city_id=city_id,
                            ward=CITY_MAP.get(city_id, ""),
                            city_page=f"{city_id}_{page_no}",
                            page_url=page_url,
                            detail_url=detail_url,
                            building_name=building_name,
                            address=_fact(facts, "住所", "所在地"),
                            access_text=_fact(facts, "交通", "アクセス"),
                            built_text=_fact(facts, "築年数", "築年月", "築"),
                            building_floor_count_text=_fact(facts, "階建て", "建物階数"),
                            total_units_text=_fact(facts, "総戸数"),
                            price_or_rent_text=sale["price_or_rent_text"],
                            fee_text="",
                            tsubo_unit_price_text=sale["tsubo_unit_price_text"],
                            deposit_text="",
                            key_money_text="",
                            area_text=sale["area_text"],
                            layout_text=sale["layout_text"],
                            floor_text=sale["floor_text"],
                            direction_text=sale["direction_text"],
                        )
                    )

    return rows, {"cards": len(cards), "rows": len(rows)}


def _cache_path(cache_dir: Path, url: str) -> Path:
    return cache_dir / f"{hashlib.sha1(url.encode('utf-8')).hexdigest()}.html"


def fetch_html(session: requests.Session, url: str, cache_dir: Path, *, retry_count: int, sleep_sec: float) -> str:
    path = _cache_path(cache_dir, url)
    if path.exists():
        return path.read_text(encoding="utf-8")

    last_error: Exception | None = None
    for attempt in range(retry_count + 1):
        try:
            response = session.get(url, timeout=20)
            response.raise_for_status()
            response.encoding = response.encoding or "utf-8"
            html = response.text
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html, encoding="utf-8")
            return html
        except Exception as err:  # noqa: BLE001
            last_error = err
            if attempt < retry_count:
                time.sleep(sleep_sec)
    raise RuntimeError(f"fetch failed: {url} ({last_error})")


def _write_list_csv(rows: list[ListRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(LIST_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _parse_total_units(value: str) -> str:
    m = re.search(r"(\d+)", normalize_space(value).replace(",", ""))
    return m.group(1) if m else ""


def _to_facts_rows(rows: list[ListRow]) -> list[dict[str, str]]:
    dedup: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (row.kind, f"{row.building_name}|{row.address}")
        if key in dedup:
            continue
        dedup[key] = {
            "building_name": row.building_name,
            "address": row.address,
            "access_info": row.access_text,
            "built_text": row.built_text,
            "floor_count_text": row.building_floor_count_text,
            "total_units": _parse_total_units(row.total_units_text),
            "evidence_id": f"mansion_review:{row.detail_url or row.page_url}",
        }
    return list(dedup.values())


def _write_facts_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(FACTS_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def _extract_man_value(text: str) -> str:
    normalized = normalize_space(text).replace(",", "")
    if not normalized:
        return ""
    man = re.search(r"(\d+(?:\.\d+)?)\s*万円", normalized)
    if man:
        return man.group(1)
    yen = re.search(r"(\d+)\s*円", normalized)
    if yen:
        value = int(yen.group(1)) / 10000
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return ""


def _split_chintai_rent_and_fee(price_or_rent_text: str, fee_text: str) -> tuple[str, str]:
    rent_man = _extract_man_value(price_or_rent_text)
    fee_man = _extract_man_value(fee_text)
    if fee_man:
        return rent_man, fee_man

    normalized = normalize_space(price_or_rent_text)
    if not normalized:
        return rent_man, ""

    paren = re.search(r"[（(]\s*([^)）]+)\s*[)）]", normalized)
    if not paren:
        return rent_man, ""

    fee_raw = normalize_space(paren.group(1))
    if _is_empty_fee_text(fee_raw):
        return rent_man, ""
    fee_from_paren = _extract_man_value(fee_raw)
    return rent_man, fee_from_paren


def _is_empty_fee_text(text: str) -> bool:
    normalized = normalize_space(text)
    if not normalized:
        return True
    ascii_norm = normalized.lower().replace("　", " ")
    if re.fullmatch(r"[\-ー−－]+(?:\s*円)?", ascii_norm):
        return True
    return ascii_norm in {"なし", "無し", "無", "-"}


def _calc_sqm_unit_price_text(price_text: str, area_text: str) -> str:
    price_man = _extract_man_value(price_text)
    area_sqm = _extract_area_sqm(area_text)
    if not price_man or not area_sqm:
        return ""
    try:
        price = Decimal(price_man)
        area = Decimal(area_sqm)
        if area <= 0:
            return ""
        sqm = (price / area).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:  # noqa: BLE001
        return ""
    sqm_text = format(sqm, "f").rstrip("0").rstrip(".")
    return f"{sqm_text}万円/m²"


def _extract_area_sqm(text: str) -> str:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:㎡|m²|m2)", normalize_space(text))
    return m.group(1) if m else ""


def _listing_evidence_id(row: ListRow) -> str:
    payload = "|".join(
        normalize_space(getattr(row, k))
        for k in (
            "kind",
            "price_or_rent_text",
            "fee_text",
            "tsubo_unit_price_text",
            "deposit_text",
            "key_money_text",
            "area_text",
            "layout_text",
            "floor_text",
            "direction_text",
        )
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"mansion_review:{row.detail_url or row.page_url}#l={digest}"


def _to_master_rows(rows: list[ListRow], updated_at: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows:
        rent_man = _extract_man_value(row.price_or_rent_text)
        fee_man = ""
        if row.kind == "chintai":
            rent_man, fee_man = _split_chintai_rent_and_fee(row.price_or_rent_text, row.fee_text)
        raw_fields = [
            ("kind", row.kind),
            ("賃料/価格", row.price_or_rent_text),
            ("管理費", row.fee_text),
            ("㎡単価", row.tsubo_unit_price_text),
            ("敷金", row.deposit_text),
            ("礼金", row.key_money_text),
            ("専有面積", row.area_text),
            ("間取り", row.layout_text),
            ("所在階", row.floor_text),
            ("向き", row.direction_text),
            ("住所", row.address),
            ("交通", row.access_text),
            ("築年数", row.built_text),
            ("階建て", row.building_floor_count_text),
            ("総戸数", row.total_units_text),
            ("一覧URL", row.page_url),
            ("詳細URL", row.detail_url),
        ]
        raw_block = " | ".join(f"{k}:{normalize_space(v)}" for k, v in raw_fields if normalize_space(v))
        out.append(
            {
                "page": row.detail_url or row.page_url,
                "category": row.kind,
                "updated_at": updated_at,
                "building_name": row.building_name,
                "room": "",
                "address": row.address,
                "rent_man": rent_man,
                "fee_man": fee_man,
                "floor": row.floor_text,
                "layout": row.layout_text,
                "area_sqm": _extract_area_sqm(row.area_text),
                "availability_raw": "",
                "built_raw": row.built_text,
                "age_years": "",
                "structure": "",
                "built_year_month": "",
                "built_age_years": "",
                "availability_date": "",
                "availability_flag_immediate": "",
                "structure_raw": "",
                "raw_block": raw_block,
                "evidence_id": _listing_evidence_id(row),
            }
        )
    return out


def _write_master_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(MASTER_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def run_crawl(
    *,
    city_ids: list[str],
    kinds: list[str],
    out_root: Path,
    cache_dir: Path,
    sleep_sec: float,
    max_pages: int,
    retry_count: int,
    user_agent: str,
) -> tuple[Path, dict[str, Path], dict[str, object]]:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_dir = out_root / timestamp

    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})

    all_rows: list[ListRow] = []
    stats: dict[str, object] = {
        "pages_total": 0,
        "rows_total": 0,
        "rows_by_kind": {},
        "unique_detail_url_by_kind": {},
        "errors": [],
    }

    for kind in kinds:
        for city_id in city_ids:
            try:
                first_html = fetch_html(
                    session,
                    build_city_page_url(kind, city_id, 1),
                    cache_dir,
                    retry_count=retry_count,
                    sleep_sec=sleep_sec,
                )
                total_pages = parse_max_page(first_html, kind=kind, city_id=city_id)
                if max_pages > 0:
                    total_pages = min(total_pages, max_pages)

                for page_no in range(1, total_pages + 1):
                    url = build_city_page_url(kind, city_id, page_no)
                    html = first_html if page_no == 1 else fetch_html(
                        session,
                        url,
                        cache_dir,
                        retry_count=retry_count,
                        sleep_sec=sleep_sec,
                    )
                    rows, page_stats = parse_list_page(html, url, kind, city_id, page_no)
                    all_rows.extend(rows)
                    stats["pages_total"] = int(stats["pages_total"]) + 1
                    print(f"[INFO] kind={kind} city_id={city_id} page={page_no}/{total_pages} rows={page_stats['rows']}")
                    time.sleep(sleep_sec)
            except Exception as err:  # noqa: BLE001
                casted = stats["errors"]
                assert isinstance(casted, list)
                casted.append({"kind": kind, "city_id": city_id, "error": str(err)})

    run_dir.mkdir(parents=True, exist_ok=True)
    list_csv = run_dir / f"mansion_review_list_{timestamp}.csv"
    _write_list_csv(all_rows, list_csv)
    facts_csv = run_dir / "building_facts.csv"
    master_csv = run_dir / "mansion_review_master_import.csv"
    _write_facts_csv(_to_facts_rows(all_rows), facts_csv)
    _write_master_csv(_to_master_rows(all_rows, datetime.utcnow().strftime("%Y/%m/%d %H:%M")), master_csv)

    rows_by_kind: dict[str, int] = {}
    detail_urls_by_kind: dict[str, set[str]] = {}
    for row in all_rows:
        rows_by_kind[row.kind] = rows_by_kind.get(row.kind, 0) + 1
        detail_urls_by_kind.setdefault(row.kind, set())
        if row.detail_url:
            detail_urls_by_kind[row.kind].add(row.detail_url)
    stats["rows_total"] = len(all_rows)
    stats["rows_by_kind"] = rows_by_kind
    stats["unique_detail_url_by_kind"] = {k: len(v) for k, v in detail_urls_by_kind.items()}

    (run_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs = {
        "list_csv": list_csv,
        "building_facts_csv": facts_csv,
        "master_import_csv": master_csv,
    }
    return run_dir, outputs, stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl mansion-review city list pages and export CSV")
    parser.add_argument("--city-ids", default="1616,1619")
    parser.add_argument("--kinds", default="chintai,mansion")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    parser.add_argument("--sleep-sec", type=float, default=0.7)
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--retry-count", type=int, default=2)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    args = parser.parse_args()

    city_ids = parse_csv_arg(args.city_ids)
    kinds = parse_csv_arg(args.kinds)

    run_dir, outputs, stats = run_crawl(
        city_ids=city_ids,
        kinds=kinds,
        out_root=Path(args.out_dir),
        cache_dir=Path(args.cache_dir),
        sleep_sec=args.sleep_sec,
        max_pages=args.max_pages,
        retry_count=args.retry_count,
        user_agent=args.user_agent,
    )

    print(f"[OK] pages_total={stats['pages_total']}")
    print(f"[OK] rows_total={stats['rows_total']}")
    for kind in kinds:
        print(f"[OK] kind={kind} rows={stats.get('rows_by_kind', {}).get(kind, 0)}")
        print(f"[OK] kind={kind} unique_detail_url={stats.get('unique_detail_url_by_kind', {}).get(kind, 0)}")
    print(f"[OK] list_csv={outputs['list_csv']}")
    print(f"[OK] building_facts_csv={outputs['building_facts_csv']}")
    print(f"[OK] master_import_csv={outputs['master_import_csv']}")
    print(f"[OK] stats={run_dir / 'stats.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
