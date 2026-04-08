from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

import requests
from selectolax.parser import HTMLParser, Node

DEFAULT_OUT = Path("tmp/manual/outputs/mansion_review")
DEFAULT_CACHE = Path("tmp/manual/cache/mansion_review")
BASE_URL = "https://www.mansion-review.jp"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

CITY_MAP = {
    "1616": "門司区",
    "1619": "小倉北区",
}


@dataclass
class ListRow:
    kind: str
    city_id: str
    ward: str
    city_page: str
    page_url: str
    building_name: str
    address: str
    detail_url: str
    price_or_rent_text: str
    layout_text: str
    area_text: str
    floor_text: str
    fee_text: str
    repair_fund_text: str
    deposit_text: str
    key_money_text: str
    direction_text: str
    total_units_text: str
    management_style_text: str
    access_text: str
    built_text: str
    building_floor_count_text: str


@dataclass
class ParseDebug:
    selector_hits: dict[str, int]
    selector_trace: list[str]


@dataclass
class FactsRow:
    building_name: str
    address: str
    structure: str
    access_info: str
    floor_count_text: str
    total_units: int | None
    management_style: str
    built_year_month: str
    property_kind: str
    sale_price_yen_min: int | None
    sale_price_yen_max: int | None
    sale_price_yen_avg: int | None
    sale_area_sqm_min: float | None
    sale_area_sqm_max: float | None
    sale_layout_types_json: str
    sale_listing_count: int | None
    avg_rent_yen: int | None
    rental_listing_count: int | None
    availability_label: str
    evidence_id: str
    raw_block: str


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _normalize_href(value: Any) -> str:
    if value is None:
        return ""
    return normalize_space(str(value))


def parse_csv_arg(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_city_page_url(kind: str, city_id: str, page: int) -> str:
    suffix = "" if page == 1 else f"_{page}"
    return f"{BASE_URL}/{kind}/city/{city_id}{suffix}.html"


def _build_city_path_regex(kind: str, city_id: str) -> re.Pattern[str]:
    return re.compile(rf"/(?:{re.escape(kind)})/city/{re.escape(city_id)}(?:_(\d+))?\.html(?:$|[?#])")


def _extract_page_number_from_href(href: str, kind: str, city_id: str) -> int | None:
    href = _normalize_href(href)
    if not href:
        return None
    pattern = _build_city_path_regex(kind, city_id)
    match = pattern.search(href)
    if not match:
        return None
    page_no = match.group(1)
    return 1 if page_no is None else int(page_no)


def _pick_first_text(node: Node, selectors: list[str]) -> str:
    for selector in selectors:
        picked = node.css_first(selector)
        if picked:
            txt = normalize_space(picked.text(separator=" "))
            if txt:
                return txt
    return ""


def _find_detail_url(card: Node, base_url: str, kind: str) -> str:
    def _href_is_detail_path(href: str) -> bool:
        if not href:
            return False
        return bool(re.search(r"/(?:mansion|chintai)/\d+(?:\.html)?(?:$|[?#])", href))

    def _is_noise_link(anchor: Node, href: str) -> bool:
        text = normalize_space(anchor.text(separator=" "))
        if any(token in text for token in ("全 件を表示", "全件を表示", "もっと見る", "口コミ")):
            return True
        if any(token in href for token in ("/city/", "/map", "/search", "/reviews", "/review")):
            return True
        return False

    title_link_selectors = [
        "h1 a[href]",
        "h2 a[href]",
        "h3 a[href]",
        ".property-name a[href]",
        ".mansionName a[href]",
        "a.property-name[href]",
    ]
    for selector in title_link_selectors:
        anchor = card.css_first(selector)
        if not anchor:
            continue
        href = _normalize_href(anchor.attributes.get("href", ""))
        if href.startswith("javascript:") or _is_noise_link(anchor, href):
            continue
        if _href_is_detail_path(href):
            return urljoin(base_url, href)

    for anchor in card.css("a[href]"):
        href = _normalize_href(anchor.attributes.get("href", ""))
        if not href or href.startswith("javascript:") or _is_noise_link(anchor, href):
            continue
        text = normalize_space(anchor.text(separator=" "))
        if any(token in text for token in ("詳細", "物件詳細")) and _href_is_detail_path(href):
            return urljoin(base_url, href)

    for anchor in card.css("a[href]"):
        href = _normalize_href(anchor.attributes.get("href", ""))
        if not href or href.startswith("javascript:") or _is_noise_link(anchor, href):
            continue
        if _href_is_detail_path(href):
            return urljoin(base_url, href)
    return ""


_LAYOUT_RE = re.compile(r"^(?:ワンルーム|[1-9]\d?(?:R|K|DK|LDK)|[1-9]\d?S(?:R|K|DK|LDK))(?:\s*[+＋]\s*S)?$", re.IGNORECASE)


def _extract_dl_pairs(card: Node) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for dl in card.css("dl"):
        dts = dl.css("dt")
        dds = dl.css("dd")
        for dt, dd in zip(dts, dds):
            key = normalize_space(dt.text(separator=" "))
            value = normalize_space(dd.text(separator=" "))
            if key and value:
                pairs[key] = value
    return pairs


def _normalize_fact_label(text: str) -> str:
    return normalize_space(text).replace("：", "").replace(":", "")


def _extract_building_fact_pairs(card: Node) -> dict[str, str]:
    building_labels = {"住所", "所在地", "交通", "アクセス", "築年数", "築年月", "築", "階建て", "建物階数", "総戸数"}
    blocks: list[dict[str, str]] = []

    for dl in card.css("dl"):
        block: dict[str, str] = {}
        dts = dl.css("dt")
        dds = dl.css("dd")
        for dt, dd in zip(dts, dds):
            key = _normalize_fact_label(dt.text(separator=" "))
            value = normalize_space(dd.text(separator=" "))
            if key and value:
                block[key] = value
        if block:
            blocks.append(block)

    for table in card.css("table"):
        block = {}
        for row in table.css("tr"):
            th = row.css_first("th")
            td = row.css_first("td")
            if not th or not td:
                continue
            key = _normalize_fact_label(th.text(separator=" "))
            value = normalize_space(td.text(separator=" "))
            if key and value:
                block[key] = value
        if block:
            blocks.append(block)

    if not blocks:
        return _extract_dl_pairs(card)

    def _score(block: dict[str, str]) -> int:
        return sum(1 for key, value in block.items() if key in building_labels and normalize_space(value))

    return max(blocks, key=_score)


def _extract_card_building_fact_pairs(card: Node) -> dict[str, str]:
    main_root = card.css_first(".property-detail-content_main")
    if main_root:
        pairs = _extract_building_fact_pairs(main_root)
        if pairs:
            return pairs
    main_table = card.css_first("table.property-detail-content_main")
    if main_table:
        pairs = _extract_building_fact_pairs(main_table)
        if pairs:
            return pairs
    return _extract_building_fact_pairs(card)


def _extract_labeled_value(card: Node, labels: tuple[str, ...], *, max_len: int = 60) -> str:
    dl_pairs = _extract_dl_pairs(card)
    for label in labels:
        value = _clean_short_text(dl_pairs.get(label, ""), max_len=max_len)
        if value:
            return value

    for row in card.css("tr"):
        th = row.css_first("th")
        td = row.css_first("td")
        if not th or not td:
            continue
        key = normalize_space(th.text(separator=" "))
        if not key:
            continue
        if any(label in key for label in labels):
            value = _clean_short_text(td.text(separator=" "), max_len=max_len)
            if value:
                return value
    return ""


def _extract_labeled_value_from_pairs(
    pairs: dict[str, str],
    labels: tuple[str, ...],
    *,
    max_len: int = 60,
    cleaner: Callable[[str], str] | None = None,
) -> str:
    for label in labels:
        value = pairs.get(label, "")
        if cleaner is not None:
            value = cleaner(value)
        else:
            value = _clean_short_text(value, max_len=max_len)
        if value:
            return value
    return ""


def _clean_transport_text(value: str) -> str:
    text = _clean_short_text(value, max_len=100)
    if not text:
        return ""
    if re.fullmatch(r"\d+", text):
        return ""
    if any(token in text for token in ("アクセス数", "口コミ数")):
        return ""
    if not any(token in text for token in ("駅", "徒歩", "バス", "線", "停", "分")):
        return ""
    return text


def _extract_transport_text(card: Node) -> str:
    labels = {"交通", "アクセス"}
    for dl in card.css("dl"):
        dts = dl.css("dt")
        dds = dl.css("dd")
        for dt, dd in zip(dts, dds):
            key = normalize_space(dt.text(separator=" "))
            if key not in labels:
                continue
            value = _clean_transport_text(dd.text(separator=" "))
            if value:
                return value

    for row in card.css("tr"):
        th = row.css_first("th")
        td = row.css_first("td")
        if not th or not td:
            continue
        key = normalize_space(th.text(separator=" "))
        if key not in labels:
            continue
        value = _clean_transport_text(td.text(separator=" "))
        if value:
            return value

    detail_info = card.css_first(".property-detail-content__info") or card
    for label_node in detail_info.css("dt, th"):
        key = normalize_space(label_node.text(separator=" "))
        if key not in labels:
            continue
        value_node = label_node.next
        if value_node and value_node.tag in {"dd", "td"}:
            value = _clean_transport_text(value_node.text(separator=" "))
            if value:
                return value
    return ""


def _extract_table_row_by_headers(card: Node, wanted: tuple[str, ...]) -> dict[str, str]:
    for table in card.css("table"):
        headers = [normalize_space(h.text(separator=" ")) for h in table.css("thead th")]
        if not headers:
            continue
        if not any(any(marker in h for marker in wanted) for h in headers):
            continue
        first_row = table.css_first("tbody tr") or table.css_first("tr")
        if not first_row:
            continue
        cells = [normalize_space(c.text(separator=" ")) for c in first_row.css("td")]
        if not cells:
            continue
        mapped: dict[str, str] = {}
        for idx, header in enumerate(headers):
            if idx >= len(cells):
                continue
            mapped[header] = cells[idx]
        detail_link = first_row.css_first("a[href]")
        if detail_link:
            mapped["__detail_href"] = _normalize_href(detail_link.attributes.get("href", ""))
        return mapped
    return {}


def _normalize_header_label(text: str) -> str:
    normalized = normalize_space(text)
    normalized = normalized.replace("（", "(").replace("）", ")")
    normalized = normalized.replace("　", "")
    return normalized


def _score_cell_for_header(header: str, cell: str) -> int:
    header = _normalize_header_label(header)
    cell = normalize_space(cell)
    if not cell:
        return 0
    if "賃料" in header or header == "価格":
        return 3 if re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:万円|円)", cell) else 0
    if "敷金" in header or "礼金" in header:
        return 3 if re.search(r"(?:ヶ月|か月|月|円|万円|なし|無|不要|-)", cell) else 0
    if "専有面積" in header:
        return 3 if re.search(r"\d+(?:\.\d+)?\s*(?:㎡|m²|m2)", cell) else 0
    if "間取り" in header:
        return 3 if _LAYOUT_RE.fullmatch(cell) else 0
    if "所在階" in header:
        return 3 if re.search(r"(?:地上\d+階|地下\d+階|\d+階|\d+F)", cell) else 0
    if "向き" in header:
        compact = cell.replace("向き", "")
        return 3 if re.fullmatch(r"(?:北|南|東|西){1,2}", compact) else 0
    if "坪単価" in header:
        return 3 if re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:万円|円)", cell) else 0
    if "価格評価" in header:
        return 2 if any(token in cell for token in ("高い", "普通", "安い", "評価")) else 1
    return 0


def _align_headers_and_cells(headers: list[str], cells: list[str]) -> tuple[list[str], list[str]]:
    if len(headers) == len(cells):
        return headers, cells
    if len(headers) != len(cells) + 1:
        return headers, cells

    best_headers = headers
    best_score = -1
    for drop_idx in range(len(headers)):
        candidate_headers = headers[:drop_idx] + headers[drop_idx + 1 :]
        score = sum(_score_cell_for_header(h, c) for h, c in zip(candidate_headers, cells))
        if score > best_score:
            best_score = score
            best_headers = candidate_headers
    return best_headers, cells


def _extract_list_row_cells(card: Node, kind: str) -> dict[str, str]:
    def _extract_chintai_recommend_row_by_position(table_node: Node) -> dict[str, str]:
        recommend_row = table_node.css_first("tbody.recommend_row tr") or table_node.css_first("tbody.recommend_row")
        if not recommend_row:
            return {}
        cells = [normalize_space(c.text(separator=" ")) for c in recommend_row.css("td")]
        if len(cells) < 9:
            return {}
        mapped: dict[str, str] = {
            "賃料(管理費)": cells[2],
            "敷金": cells[3],
            "礼金": cells[4],
            "専有面積": cells[5],
            "間取り": cells[6],
            "所在階": cells[7],
            "向き": cells[8],
        }
        detail_link = recommend_row.css_first("a[href]")
        if detail_link:
            mapped["__detail_href"] = _normalize_href(detail_link.attributes.get("href", ""))
        return mapped

    def _first_recommend_cells(table_node: Node) -> list[str]:
        first_row = table_node.css_first("tbody.recommend_row tr") or table_node.css_first("tbody tr") or table_node.css_first("tr")
        if not first_row:
            return []
        return [normalize_space(c.text(separator=" ")) for c in first_row.css("td")]

    def _extract_chintai_cells_by_position(cells: list[str]) -> dict[str, str]:
        if len(cells) < 7:
            return {}
        rent_idx = -1
        for idx, cell in enumerate(cells[:5]):
            if re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:万円|円)", cell):
                rent_idx = idx
                break
        if rent_idx < 0:
            return {}
        mapped: dict[str, str] = {"賃料(管理費)": cells[rent_idx]}
        if rent_idx + 1 < len(cells):
            mapped["敷金"] = cells[rent_idx + 1]
        if rent_idx + 2 < len(cells):
            mapped["礼金"] = cells[rent_idx + 2]
        if rent_idx + 3 < len(cells):
            mapped["専有面積"] = cells[rent_idx + 3]
        if rent_idx + 4 < len(cells):
            mapped["間取り"] = cells[rent_idx + 4]
        if rent_idx + 5 < len(cells):
            mapped["所在階"] = cells[rent_idx + 5]
        if rent_idx + 6 < len(cells):
            mapped["向き"] = cells[rent_idx + 6]
        return mapped

    def _is_valid_chintai_mapping(mapped: dict[str, str]) -> bool:
        rent = normalize_space(mapped.get("賃料(管理費)") or mapped.get("賃料") or "")
        area = normalize_space(mapped.get("専有面積", ""))
        layout = normalize_space(mapped.get("間取り", ""))
        floor = normalize_space(mapped.get("所在階", ""))
        return bool(
            re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:万円|円)", rent)
            and re.search(r"\d+(?:\.\d+)?\s*(?:㎡|m²|m2)", area)
            and _LAYOUT_RE.fullmatch(layout)
            and re.search(r"(?:地上\d+階|地下\d+階|\d+階|\d+F)", floor)
        )

    tables = card.css("table.recommendTable") or card.css("table")
    for table in tables:
        if kind == "chintai":
            mapped_by_position = _extract_chintai_recommend_row_by_position(table)
            if mapped_by_position.get("賃料(管理費)") or mapped_by_position.get("賃料"):
                return mapped_by_position

        headers = [_normalize_header_label(h.text(separator=" ")) for h in table.css("thead th")]
        if not headers:
            continue
        has_rent = any("賃料" in h for h in headers)
        has_price = any("価格" in h for h in headers)
        has_area = any("専有面積" in h for h in headers)
        if kind == "chintai":
            if not has_rent:
                continue
        else:
            if not (has_price and has_area):
                continue

        cells = _first_recommend_cells(table)
        if not cells:
            continue

        aligned_headers, aligned_cells = _align_headers_and_cells(list(headers), cells)

        mapped: dict[str, str] = {}
        for idx, header in enumerate(aligned_headers):
            if idx >= len(aligned_cells):
                continue
            mapped[header] = aligned_cells[idx]
        if kind == "chintai" and not _is_valid_chintai_mapping(mapped):
            positional = _extract_chintai_cells_by_position(cells)
            if positional:
                mapped.update(positional)
        first_row = table.css_first("tbody.recommend_row tr") or table.css_first("tbody tr") or table.css_first("tr")
        detail_link = first_row.css_first("a[href]") if first_row else None
        if detail_link:
            mapped["__detail_href"] = _normalize_href(detail_link.attributes.get("href", ""))
        return mapped
    return {}


def _extract_chintai_recommend_rows(card: Node) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    tables = card.css("table.recommendTable") or card.css("table")
    for table in tables:
        headers = [_normalize_header_label(h.text(separator=" ")) for h in table.css("thead th")]
        body_rows = table.css("tbody.recommend_row tr") or table.css("tbody.recommend_row")
        for tr in body_rows:
            row_cells = []
            for c in tr.css("td"):
                class_name = normalize_space(c.attributes.get("class", ""))
                if "recommend_update_row" in class_name:
                    continue
                row_cells.append(normalize_space(c.text(separator=" ")))
            if not row_cells:
                continue
            aligned_headers, aligned_cells = _align_headers_and_cells(list(headers), row_cells)
            mapped: dict[str, str] = {}
            for idx, header in enumerate(aligned_headers):
                if idx >= len(aligned_cells):
                    continue
                mapped[header] = aligned_cells[idx]
            mapped_rent = mapped.get("賃料(管理費)", "") or mapped.get("賃料", "")
            if (not re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:万円|円)", normalize_space(mapped_rent))) and len(row_cells) >= 7:
                tail = row_cells[-7:]
                mapped["賃料(管理費)"] = tail[0]
                mapped["敷金"] = tail[1]
                mapped["礼金"] = tail[2]
                mapped["専有面積"] = tail[3]
                mapped["間取り"] = tail[4]
                mapped["所在階"] = tail[5]
                mapped["向き"] = tail[6]
            detail_link = tr.css_first("a[href]")
            if detail_link:
                mapped["__detail_href"] = _normalize_href(detail_link.attributes.get("href", ""))
            rows.append(mapped)
        if rows:
            break
    return rows


def _looks_polluted_text(value: str) -> bool:
    text = normalize_space(value)
    if not text:
        return False
    if len(text) > 40:
        return True
    lowered = text.lower()
    markers = ("function", "jquery", "<script", "全 件を表示", "全件を表示", "賃料(管理費)", "敷金", "礼金", "間取り", "専有面積", "交通")
    if any(marker.lower() in lowered for marker in markers):
        return True
    return any(token in text for token in ("|", "：", ":", "。", "{", "}", ";"))


def _clean_layout_text(value: str) -> str:
    text = normalize_space(value)
    if not text or _looks_polluted_text(text):
        return ""
    if _LAYOUT_RE.fullmatch(text):
        return text
    match = re.search(r"\b([1-9]\d?\s*(?:R|K|DK|LDK|S(?:R|K|DK|LDK)))\b", text, re.IGNORECASE)
    if match:
        candidate = normalize_space(match.group(1))
        return candidate if _LAYOUT_RE.fullmatch(candidate) else ""
    return ""


def _clean_area_text(value: str) -> str:
    text = normalize_space(value)
    if not text or _looks_polluted_text(text):
        return ""
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:㎡|m²|m2)", text)
    if not match:
        return ""
    return f"{match.group(1)}㎡"


def _clean_floor_text(value: str) -> str:
    text = normalize_space(value)
    if not text or _looks_polluted_text(text):
        return ""
    match = re.search(r"(?:地上\d+階|地下\d+階|\d+階|\d+F)", text)
    return normalize_space(match.group(0)) if match else ""


def _extract_fee_text(price_or_rent_text: str) -> str:
    text = normalize_space(price_or_rent_text)
    if not text:
        return ""
    m = re.search(r"\(([^()]{1,20})\)", text)
    if not m:
        return ""
    candidate = normalize_space(m.group(1))
    return candidate if (("円" in candidate) or ("万円" in candidate)) else ""


def _clean_fee_text(value: str) -> str:
    text = _clean_short_text(value, max_len=20)
    if not text:
        return ""
    if re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:円|万円)", text):
        return text
    return ""


def _split_rent_and_fee_from_cell(value: str) -> tuple[str, str]:
    text = normalize_space(value)
    if not text:
        return "", ""

    slash_match = re.search(r"[／/]\s*([0-9][0-9,]*(?:\.\d+)?\s*(?:円|万円))", text)
    if slash_match:
        rent_line = normalize_space(re.split(r"[／/]", text, maxsplit=1)[0])
        fee_text = _clean_fee_text(slash_match.group(1))
        return rent_line, fee_text

    rent_line = normalize_space(re.split(r"[（(]", text, maxsplit=1)[0])
    fee_text = _clean_fee_text(_extract_fee_text(text))
    return rent_line or text, fee_text


def _clean_short_text(value: str, *, max_len: int = 30) -> str:
    text = normalize_space(value)
    if not text:
        return ""
    lowered = text.lower()
    blocked_markers = ("function", "jquery", "<script", "全 件を表示", "全件を表示")
    if any(marker in lowered for marker in blocked_markers):
        return ""
    if len(text) > max_len:
        return ""
    if any(token in text for token in ("|", "｜", "{", "}", ";")):
        return ""
    return text


def _clean_deposit_like_text(value: str) -> str:
    text = _clean_short_text(value, max_len=20)
    if not text:
        return ""
    if re.search(r"(?:ヶ月|か月|月|円|万円|なし|無|不要|相談|-)", text):
        return text
    return ""


def _clean_direction_text(value: str) -> str:
    text = _clean_short_text(value, max_len=10)
    if not text:
        return ""
    compact = text.replace("向き", "")
    if re.fullmatch(r"(?:北|南|東|西){1,2}", compact):
        return text
    return ""


def _find_text_with_pattern(card: Node, patterns: list[str]) -> str:
    text = normalize_space(card.text(separator=" "))
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return normalize_space(match.group(0))
    return ""


def _extract_address_like_text(text: str) -> str:
    normalized = normalize_space(text)
    if not normalized:
        return ""
    patterns = [
        r"(?:東京都|北海道|(?:京都|大阪)府|[^\s、,]{2,8}県)?[^\s、,]{1,20}(?:市|区|町|村)[^\s、,]{0,120}\d[^\s、,]{0,40}",
        r"(?:東京都|北海道|(?:京都|大阪)府|[^\s、,]{2,8}県)?[^\s、,]{1,20}(?:市|区|町|村)[^\s、,]{0,140}",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return normalize_space(match.group(0))
    return ""


def _address_has_digits(address: str) -> bool:
    return bool(re.search(r"\d", normalize_space(address)))


def _is_invalid_building_address(text: str) -> bool:
    normalized = normalize_space(text)
    if not normalized:
        return True
    lowered = normalized.lower()
    blocked_substrings = (
        "選択してください",
        "市区町村もしくは駅を1つ以上選択してください",
        "入力してください",
        "候補から選択",
        "検索",
        "autocomplete",
        "validation",
    )
    return any(token in normalized or token in lowered for token in blocked_substrings)


def _clean_building_address(text: str) -> str:
    cleaned = _strip_fukuoka_prefix(text)
    if _is_invalid_building_address(cleaned):
        return ""
    return cleaned


def detect_card_nodes(tree: HTMLParser) -> tuple[list[Node], ParseDebug]:
    selectors = [
        "li.property-detail-list-item",
        "section.property-card",
        "article.property-card",
        "li.property-card",
        "section[class*='property']",
        "article[class*='property']",
        "div[class*='property-card']",
        "li[class*='property']",
        "article[class*='bukken']",
        "section[class*='bukken']",
        "li[class*='bukken']",
    ]

    selector_hits: dict[str, int] = {}
    selector_trace: list[str] = []
    for selector in selectors:
        nodes = tree.css(selector)
        selector_hits[selector] = len(nodes)
        selector_trace.append(f"selector={selector} hits={len(nodes)}")
        if nodes:
            return nodes, ParseDebug(selector_hits=selector_hits, selector_trace=selector_trace)

    return [], ParseDebug(selector_hits=selector_hits, selector_trace=selector_trace)


def parse_list_page(html: str, page_url: str, kind: str, city_id: str, page_no: int) -> tuple[list[ListRow], ParseDebug]:
    tree = HTMLParser(html)
    cards, debug = detect_card_nodes(tree)
    rows: list[ListRow] = []

    for card in cards:
        building_pairs = _extract_card_building_fact_pairs(card)
        dl_pairs = _extract_dl_pairs(card)
        has_recommend_rows = bool(card.css("table.recommendTable tbody.recommend_row"))
        row_cells = _extract_list_row_cells(card, kind) or _extract_table_row_by_headers(card, ("賃料", "価格", "間取り", "専有面積"))
        recommend_rows = _extract_chintai_recommend_rows(card) if kind == "chintai" else []
        building_name = _pick_first_text(
            card,
            [
                "h1",
                "h2",
                "h3",
                ".property-name",
                ".bukkenName",
                ".mansionName",
                "a[title]",
                "a",
            ],
        )
        address = _clean_building_address(_extract_labeled_value_from_pairs(building_pairs, ("住所", "所在地"), max_len=120))
        if not address:
            address = _pick_first_text(card, [".address", "dd.address", "[class*='address']"])
        if not address:
            address = _extract_address_like_text(card.text(separator=" "))
        address = _strip_fukuoka_prefix(address)

        price_or_rent_text = ""
        if kind == "chintai":
            rent_cell = row_cells.get("賃料(管理費)", "") or row_cells.get("賃料", "")
            price_or_rent_text, rent_fee_from_cell = _split_rent_and_fee_from_cell(rent_cell)
            if not re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:万円|円)", price_or_rent_text):
                price_or_rent_text = ""
        else:
            rent_fee_from_cell = ""
            price_or_rent_text = row_cells.get("価格", "")
        if not price_or_rent_text and not (kind == "chintai" and has_recommend_rows):
            price_or_rent_text = _pick_first_text(
                card,
                [
                    ".price",
                    ".rent",
                    ".money",
                ],
            )
        if not price_or_rent_text and not (kind == "chintai" and has_recommend_rows):
            for key in ("賃料(管理費)", "賃料", "価格"):
                if key in row_cells:
                    price_or_rent_text = row_cells[key]
                    break
        if kind == "chintai" and has_recommend_rows and not normalize_space(price_or_rent_text):
            print(
                f"[WARN] chintai recommend_row detected but rent not parsed: "
                f"city_id={city_id} page_no={page_no} page_url={page_url}"
            )
        if not price_or_rent_text and not (kind == "chintai" and has_recommend_rows):
            price_or_rent_text = _find_text_with_pattern(card, [r"\d[\d,]*(?:\.\d+)?\s*(?:万円|円)"])

        layout_text = _clean_layout_text(_pick_first_text(card, [".layout", "[class*='layout']"]))
        if not layout_text:
            layout_text = _clean_layout_text(row_cells.get("間取り", ""))
        if not layout_text:
            layout_text = _clean_layout_text(_find_text_with_pattern(card, [r"\d\s*[SLDKR]+"]))

        area_text = _clean_area_text(_pick_first_text(card, [".area", "[class*='area']"]))
        if not area_text:
            area_text = _clean_area_text(row_cells.get("専有面積", ""))
        if not area_text:
            area_text = _clean_area_text(_find_text_with_pattern(card, [r"\d+(?:\.\d+)?\s*(?:㎡|m²|m2)"]))

        floor_text = _clean_floor_text(_pick_first_text(card, [".floor", "[class*='floor']"]))
        if not floor_text:
            floor_text = _clean_floor_text(row_cells.get("所在階", ""))
        if not floor_text:
            floor_text = _clean_floor_text(dl_pairs.get("建物階数", ""))
        if not floor_text:
            floor_text = _clean_floor_text(_find_text_with_pattern(card, [r"(?:\d+階|\d+F|地上\d+階|地下\d+階)"]))

        detail_url = _find_detail_url(card, page_url, kind)
        if not detail_url and row_cells.get("__detail_href"):
            detail_url = urljoin(page_url, row_cells["__detail_href"])

        fee_text = ""
        if kind == "chintai":
            fee_text = _clean_fee_text(
                row_cells.get("管理費")
                or row_cells.get("管理費(共益費)")
                or row_cells.get("管理費/共益費")
                or row_cells.get("共益費")
                or dl_pairs.get("管理費")
                or dl_pairs.get("共益費")
            )
            if not fee_text:
                fee_text = rent_fee_from_cell
            if not fee_text:
                fee_text = _clean_fee_text(_extract_fee_text(price_or_rent_text))
        repair_fund_text = ""
        deposit_text = (
            _clean_deposit_like_text(row_cells.get("敷金", "") or dl_pairs.get("敷金", "") or dl_pairs.get("保証金", ""))
            if kind == "chintai"
            else ""
        )
        key_money_text = (
            _clean_deposit_like_text(row_cells.get("礼金", "") or dl_pairs.get("礼金", "") or dl_pairs.get("敷引", ""))
            if kind == "chintai"
            else ""
        )
        direction_text = _clean_direction_text(row_cells.get("向き", "") or dl_pairs.get("向き", ""))
        total_units_text = _extract_labeled_value_from_pairs(building_pairs, ("総戸数",), max_len=20)
        management_style_text = ""
        access_text = _extract_labeled_value_from_pairs(building_pairs, ("交通", "アクセス"), cleaner=_clean_transport_text, max_len=100)
        built_text = _extract_labeled_value_from_pairs(building_pairs, ("築年数", "築年月", "築"), max_len=30)
        building_floor_count_text = _extract_labeled_value_from_pairs(building_pairs, ("階建て", "建物階数"), max_len=20)

        if not building_name:
            continue

        source_rows = recommend_rows if recommend_rows else [row_cells]
        for source_row in source_rows:
            row_price_or_rent_text = price_or_rent_text
            row_fee_text = fee_text
            if kind == "chintai":
                source_rent = source_row.get("賃料(管理費)", "") or source_row.get("賃料", "")
                source_price_or_rent_text, source_rent_fee_from_cell = _split_rent_and_fee_from_cell(source_rent)
                if source_price_or_rent_text:
                    row_price_or_rent_text = source_price_or_rent_text
                if not re.search(r"\d[\d,]*(?:\.\d+)?\s*(?:万円|円)", row_price_or_rent_text):
                    row_price_or_rent_text = ""
                row_fee_text = _clean_fee_text(
                    source_row.get("管理費")
                    or source_row.get("管理費(共益費)")
                    or source_row.get("管理費/共益費")
                    or source_row.get("共益費")
                )
                if not row_fee_text:
                    row_fee_text = source_rent_fee_from_cell or fee_text
                if not row_fee_text and row_price_or_rent_text:
                    row_fee_text = _clean_fee_text(_extract_fee_text(row_price_or_rent_text))
            if kind == "chintai" and recommend_rows:
                row_layout_text = _clean_layout_text(source_row.get("間取り", ""))
                row_area_text = _clean_area_text(source_row.get("専有面積", ""))
                row_floor_text = _clean_floor_text(source_row.get("所在階", ""))
                row_deposit_text = _clean_deposit_like_text(source_row.get("敷金", ""))
                row_key_money_text = _clean_deposit_like_text(source_row.get("礼金", ""))
                row_direction_text = _clean_direction_text(source_row.get("向き", ""))
            else:
                row_layout_text = _clean_layout_text(source_row.get("間取り", "")) or layout_text
                row_area_text = _clean_area_text(source_row.get("専有面積", "")) or area_text
                row_floor_text = _clean_floor_text(source_row.get("所在階", "")) or floor_text
                row_deposit_text = _clean_deposit_like_text(source_row.get("敷金", "") or deposit_text) if kind == "chintai" else ""
                row_key_money_text = _clean_deposit_like_text(source_row.get("礼金", "") or key_money_text) if kind == "chintai" else ""
                row_direction_text = _clean_direction_text(source_row.get("向き", "") or direction_text)
            row_detail_url = detail_url
            if source_row.get("__detail_href"):
                row_detail_url = urljoin(page_url, source_row["__detail_href"])

            rows.append(
                ListRow(
                    kind=kind,
                    city_id=city_id,
                    ward=CITY_MAP.get(city_id, ""),
                    city_page=f"{city_id}_{page_no}",
                    page_url=page_url,
                    building_name=building_name,
                    address=address,
                    detail_url=row_detail_url,
                    price_or_rent_text=row_price_or_rent_text,
                    layout_text=row_layout_text,
                    area_text=row_area_text,
                    floor_text=row_floor_text,
                    fee_text=row_fee_text,
                    repair_fund_text=repair_fund_text,
                    deposit_text=row_deposit_text,
                    key_money_text=row_key_money_text,
                    direction_text=row_direction_text,
                    total_units_text=total_units_text,
                    management_style_text=management_style_text,
                    access_text=access_text,
                    built_text=built_text,
                    building_floor_count_text=building_floor_count_text,
                )
            )

    return rows, debug


def parse_max_page(html: str, kind: str, city_id: str) -> int:
    tree = HTMLParser(html)
    max_page = 1
    for href_node in tree.css("a[href]"):
        href = _normalize_href(href_node.attributes.get("href", ""))
        page = _extract_page_number_from_href(href, kind, city_id)
        if page is not None:
            max_page = max(max_page, page)
    return max_page


def find_next_page_url(html: str, current_url: str, kind: str, city_id: str, current_page: int) -> str | None:
    tree = HTMLParser(html)
    current_page_plus_one = current_page + 1

    for anchor in tree.css("a[href]"):
        href = _normalize_href(anchor.attributes.get("href", ""))
        if not href:
            continue
        rel = normalize_space(anchor.attributes.get("rel", "")).lower()
        class_name = normalize_space(anchor.attributes.get("class", "")).lower()
        text = normalize_space(anchor.text(separator=" ")).lower()

        has_next_hint = (
            rel == "next"
            or " next " in f" {class_name} "
            or "pager-next" in class_name
            or text in {"次へ", "次", "next", ">", "›", "≫"}
        )
        if not has_next_hint:
            continue

        page = _extract_page_number_from_href(href, kind, city_id)
        if page is None or page < current_page_plus_one:
            continue
        return urljoin(current_url, href)

    guessed_next_url = build_city_page_url(kind, city_id, current_page_plus_one)
    return guessed_next_url


def _write_fetch_error_debug(debug_dir: Path, out_dir: Path, kind: str, city_id: str, page: int, url: str, err: Exception) -> str:
    debug_name = f"{kind}_{city_id}_page{page}_fetch_error.html"
    debug_path = debug_dir / debug_name
    error_text = normalize_space(str(err))
    debug_path.write_text(
        (
            "<html><body>"
            "<h1>Fetch failed</h1>"
            f"<p>url: {url}</p>"
            f"<p>error: {error_text}</p>"
            "</body></html>"
        ),
        encoding="utf-8",
    )
    return str(debug_path.relative_to(out_dir))


def cache_path_for_url(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.html"


def fetch_html(
    session: requests.Session,
    url: str,
    cache_dir: Path,
    *,
    retry_count: int,
    sleep_sec: float,
) -> tuple[str, bool]:
    cache_file = cache_path_for_url(cache_dir, url)
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8", errors="ignore"), True

    cache_dir.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None

    for attempt in range(retry_count + 1):
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
            response.encoding = response.apparent_encoding
            html = response.text
            cache_file.write_text(html, encoding="utf-8")
            return html, False
        except requests.RequestException as err:  # noqa: PERF203
            last_error = err
            if attempt < retry_count:
                time.sleep(max(sleep_sec, 0.1))

    if last_error is None:
        raise RuntimeError(f"failed to fetch url: {url}")
    raise last_error


def write_csv(rows: list[ListRow], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(asdict(rows[0]).keys()) if rows else list(ListRow.__annotations__.keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))




def _strip_fukuoka_prefix(address: str) -> str:
    text = normalize_space(address)
    return re.sub(r"^福岡県", "", text)


def _parse_built_year_month(text: str) -> str:
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", text)
    if not m:
        return ""
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"


def _parse_price_to_yen(text: str) -> int | None:
    t = normalize_space(text).replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*万円", t)
    if m:
        return int(float(m.group(1)) * 10000)
    m = re.search(r"(\d+)\s*円", t)
    if m:
        return int(m.group(1))
    return None


def _parse_area_sqm(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:㎡|m²|m2)", normalize_space(text))
    return float(m.group(1)) if m else None


def _extract_built_text(card: Node, full_text: str) -> str:
    built_text = _extract_labeled_value(card, ("築年数", "築年月", "築"), max_len=30)
    if built_text:
        return built_text

    m_age = re.search(r"(築(?:年数)?\s*[:：]?\s*\d{1,3}\s*年)", full_text)
    if m_age:
        return normalize_space(m_age.group(1))

    m_built = re.search(r"(\d{4}\s*年\s*\d{1,2}\s*月)", full_text)
    if m_built:
        return normalize_space(m_built.group(1))
    return ""


def _build_facts_raw_block(
    *,
    address: str,
    access_info: str,
    built_text: str,
    floor_count_text: str,
    total_units_text: str,
) -> str:
    lines: list[str] = []
    if address:
        lines.append(f"住所: {address}")
    if access_info:
        lines.append(f"交通: {access_info}")
    if built_text:
        lines.append(f"築年数: {built_text}")
    if floor_count_text:
        lines.append(f"階建て: {floor_count_text}")
    if total_units_text:
        lines.append(f"総戸数: {total_units_text}")
    return normalize_space("\n".join(lines))[:400]


def _extract_recommend_rows(card: Node) -> tuple[list[int], list[float], list[str], int]:
    prices: list[int] = []
    areas: list[float] = []
    layouts: list[str] = []

    table = card.css_first("table.recommendTable")
    if not table:
        return prices, areas, layouts, 0

    headers = [normalize_space(th.text(separator=" ")) for th in table.css("thead th")]
    idx_price = idx_area = idx_layout = -1
    for i, h in enumerate(headers):
        if "価格" in h:
            idx_price = i
        elif "専有面積" in h:
            idx_area = i
        elif "間取り" in h:
            idx_layout = i

    body_rows = table.css("tbody.recommend_row tr") or table.css("tbody.recommend_row")
    row_count = len(body_rows)
    for tr in body_rows:
        cells = tr.css("td")
        if idx_price >= 0 and idx_price < len(cells):
            p = _parse_price_to_yen(cells[idx_price].text(separator=" "))
            if p is not None:
                prices.append(p)
        if idx_area >= 0 and idx_area < len(cells):
            a = _parse_area_sqm(cells[idx_area].text(separator=" "))
            if a is not None:
                areas.append(a)
        if idx_layout >= 0 and idx_layout < len(cells):
            l = normalize_space(cells[idx_layout].text(separator=" "))
            if l:
                layouts.append(l)

    return prices, areas, sorted(set(layouts)), row_count


def parse_list_card_facts(card: Node, kind: str, detail_url: str, fallback_name: str, fallback_address: str) -> FactsRow:
    full_text = normalize_space(card.text(separator=" "))
    building_name = _pick_first_text(card, ["h1", "h2", "h3", ".mansionName", ".property-name", "a[title]", "a"]) or normalize_space(fallback_name)
    building_pairs = _extract_building_fact_pairs(card)
    address = _clean_building_address(_extract_labeled_value_from_pairs(building_pairs, ("住所", "所在地"), max_len=120))
    if not address:
        address = _clean_building_address(fallback_address)
    if not address:
        address = _clean_building_address(_pick_first_text(card, [".address", "dd.address"]))
    if not address:
        address = _clean_building_address(_extract_address_like_text(full_text))

    built_year_month = _parse_built_year_month(full_text)
    evidence_id = f"mansion_review:{detail_url or building_name}"

    avg_price = None
    m_avg_price = re.search(r"平均価格\s*[:：]?\s*(\d+(?:\.\d+)?)\s*万円", full_text)
    if m_avg_price:
        avg_price = int(float(m_avg_price.group(1)) * 10000)

    avg_rent = None
    m_avg_rent = re.search(r"平均賃料\s*[:：]?\s*(\d+(?:\.\d+)?)\s*万円", full_text)
    if m_avg_rent:
        avg_rent = int(float(m_avg_rent.group(1)) * 10000)

    prices, areas, layouts, rec_count = _extract_recommend_rows(card)

    sale_min = min(prices) if prices else avg_price
    sale_max = max(prices) if prices else avg_price

    property_kind = "bunjo" if kind == "mansion" else "chintai"
    structure = "RC" if property_kind == "bunjo" else ""
    access_info = _extract_labeled_value_from_pairs(building_pairs, ("交通", "アクセス"), cleaner=_clean_transport_text, max_len=100)
    built_text = _extract_labeled_value_from_pairs(building_pairs, ("築年数", "築年月", "築"), max_len=30)
    floor_count_text = _extract_labeled_value_from_pairs(building_pairs, ("階建て", "建物階数"), max_len=20)
    total_units = None
    total_units_text = _extract_labeled_value_from_pairs(building_pairs, ("総戸数",), max_len=20)
    m_units = re.search(r"(\d+)", total_units_text) if total_units_text else None
    if m_units:
        total_units = int(m_units.group(1))
    management_style = _find_text_with_pattern(card, [r"管理方式\s*[:：]?\s*[^\s、,]{1,20}"])

    return FactsRow(
        building_name=building_name,
        address=address,
        structure=structure,
        access_info=access_info,
        floor_count_text=floor_count_text,
        total_units=total_units,
        management_style=management_style,
        built_year_month=built_year_month,
        property_kind=property_kind,
        sale_price_yen_min=sale_min if property_kind == "bunjo" else None,
        sale_price_yen_max=sale_max if property_kind == "bunjo" else None,
        sale_price_yen_avg=avg_price if property_kind == "bunjo" else None,
        sale_area_sqm_min=min(areas) if (areas and property_kind == "bunjo") else None,
        sale_area_sqm_max=max(areas) if (areas and property_kind == "bunjo") else None,
        sale_layout_types_json=json.dumps(layouts, ensure_ascii=False) if (layouts and property_kind == "bunjo") else "",
        sale_listing_count=rec_count if property_kind == "bunjo" else None,
        avg_rent_yen=avg_rent if property_kind == "chintai" else None,
        rental_listing_count=rec_count if property_kind == "chintai" else None,
        availability_label="",
        evidence_id=evidence_id,
        raw_block=_build_facts_raw_block(
            address=address,
            access_info=access_info,
            built_text=built_text,
            floor_count_text=floor_count_text,
            total_units_text=total_units_text,
        ),
    )

def parse_detail_facts(html: str, detail_url: str, fallback_name: str, fallback_address: str) -> FactsRow:
    tree = HTMLParser(html)
    full_text = normalize_space(tree.text(separator=" "))

    title_node = tree.css_first("h1, h2, .mansionName, .property-name")
    title_name = normalize_space(title_node.text(separator=" ")) if title_node else ""
    building_name = title_name or normalize_space(fallback_name)

    address = ""
    address_candidates = [
        tree.css_first(".address"),
        tree.css_first("dd.address"),
        tree.css_first("[class*='address']"),
    ]
    for node in address_candidates:
        if node:
            picked = normalize_space(node.text(separator=" "))
            if picked:
                address = picked
                break
    if not address:
        address = _extract_address_like_text(full_text)
    if not address:
        address = normalize_space(fallback_address)
    address = _clean_building_address(address)

    structure = ""
    m_structure = re.search(r"(?:構造|建物構造)\s*[:：]?\s*([^\s、,]{1,20})", full_text)
    if m_structure:
        structure = normalize_space(m_structure.group(1))
    else:
        m_abbrev = re.search(r"\b(?:RC|SRC|HRC|S|木造|鉄骨造|鉄筋コンクリート造|鉄骨鉄筋コンクリート造)\b", full_text)
        if m_abbrev:
            structure = normalize_space(m_abbrev.group(0))

    age_years: int | None = None
    m_age = re.search(r"築(?:年数)?\s*[:：]?\s*(\d{1,3})\s*年", full_text)
    if m_age:
        age_years = int(m_age.group(1))
    else:
        m_built = re.search(r"(?:築年月|建築年月|竣工)\s*[:：]?\s*(\d{4})[/-年\.]\s*(\d{1,2})", full_text)
        if m_built:
            built_year = int(m_built.group(1))
            today = datetime.now()
            age_years = max(today.year - built_year, 0)

    availability_label = ""
    if "即入居" in full_text:
        availability_label = "即入居"
    else:
        m_avail = re.search(r"(?:入居(?:可能|可)?(?:時期)?|空室情報)\s*[:：]?\s*([^\s、,]{1,20})", full_text)
        if m_avail:
            availability_label = normalize_space(m_avail.group(1))
        else:
            for token in ("空室", "相談", "退去予定"):
                if token in full_text:
                    availability_label = token
                    break

    evidence_id = f"mansion_review:{detail_url}"
    raw_block = full_text[:1200]
    return FactsRow(
        building_name=building_name,
        address=address,
        structure=structure,
        access_info=_extract_transport_text(tree.root),
        floor_count_text=_extract_labeled_value(tree.root, ("階建て", "建物階数"), max_len=20)
        or _find_text_with_pattern(tree.root, [r"(?:地上)?\d+階(?:建)?"]),
        total_units=(int(m.group(1)) if (m := re.search(r"総戸数\s*[:：]?\s*(\d+)", full_text)) else None),
        management_style=(normalize_space(m.group(1)) if (m := re.search(r"管理方式\s*[:：]?\s*([^\s、,]{1,20})", full_text)) else ""),
        built_year_month=_parse_built_year_month(full_text),
        property_kind="",
        sale_price_yen_min=None,
        sale_price_yen_max=None,
        sale_price_yen_avg=None,
        sale_area_sqm_min=None,
        sale_area_sqm_max=None,
        sale_layout_types_json="",
        sale_listing_count=None,
        avg_rent_yen=None,
        rental_listing_count=None,
        availability_label=availability_label,
        evidence_id=evidence_id,
        raw_block=raw_block,
    )


def write_facts_csv(rows: list[FactsRow], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8-sig", newline="") as fp:
        fieldnames = list(FactsRow.__annotations__.keys())
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = asdict(row)
            for key, value in list(payload.items()):
                if value is None:
                    payload[key] = ""
            writer.writerow(payload)


def run_crawl(
    city_ids: list[str],
    kinds: list[str],
    mode: str,
    out_root: Path,
    cache_dir: Path,
    sleep_sec: float,
    max_pages: int,
    retry_count: int,
    user_agent: str,
    auto_max_threshold: int = 200,
) -> tuple[Path, Path, dict[str, Any]]:
    if mode not in {"list", "facts"}:
        raise ValueError(f"Unsupported mode: {mode}. expected one of list,facts")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = out_root / timestamp
    debug_dir = out_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept-Language": "ja,en;q=0.8",
        }
    )

    all_rows: list[ListRow] = []
    all_facts_rows: list[FactsRow] = []
    facts_coverage: dict[tuple[str, str], dict[str, int]] = {}
    stats: dict[str, Any] = {
        "timestamp": timestamp,
        "mode": mode,
        "city_ids": city_ids,
        "kinds": kinds,
        "sleep_sec": sleep_sec,
        "max_pages_arg": max_pages,
        "pages_total": 0,
        "rows_total": 0,
        "cache_hits": 0,
        "zero_extract_pages": [],
        "errors": [],
    }

    for kind in kinds:
        for city_id in city_ids:
            page1_url = build_city_page_url(kind, city_id, 1)
            try:
                html, from_cache = fetch_html(
                    session,
                    page1_url,
                    cache_dir,
                    retry_count=retry_count,
                    sleep_sec=sleep_sec,
                )
            except Exception as err:  # noqa: BLE001
                debug_html = _write_fetch_error_debug(debug_dir, out_dir, kind, city_id, 1, page1_url, err)
                stats["errors"].append(
                    {
                        "kind": kind,
                        "city_id": city_id,
                        "page": 1,
                        "url": page1_url,
                        "error": f"fetch failed: {err}",
                        "debug_html": debug_html,
                    }
                )
                continue

            if from_cache:
                stats["cache_hits"] += 1

            if max_pages > 0:
                total_pages = max_pages
                auto_mode = False
                stats["autopage"] = stats.get("autopage", [])
                stats["autopage"].append({"kind": kind, "city_id": city_id, "mode": "fixed", "max_pages": total_pages})
            else:
                detected_pages = parse_max_page(html, kind, city_id)
                total_pages = max(detected_pages, 1)
                auto_mode = total_pages <= auto_max_threshold
                autopage_mode = "max_page_links" if auto_mode else "follow_next"
                stats["autopage"] = stats.get("autopage", [])
                stats["autopage"].append(
                    {
                        "kind": kind,
                        "city_id": city_id,
                        "mode": autopage_mode,
                        "detected_max_page": total_pages,
                        "threshold": auto_max_threshold,
                    }
                )

            page = 1
            page_url = page1_url
            page_html = html
            cache_hit_for_log = from_cache
            prev_detail_urls: set[str] | None = None
            should_continue = True

            while should_continue:
                if max_pages > 0 and page > total_pages:
                    break
                if max_pages == 0 and auto_mode and page > total_pages:
                    break

                rows, parse_debug = parse_list_page(page_html, page_url, kind, city_id, page)
                stats["pages_total"] += 1
                all_rows.extend(rows)
                if mode == "facts":
                    tree = HTMLParser(page_html)
                    facts_cards, _ = detect_card_nodes(tree)
                    for card in facts_cards:
                        detail_url = _find_detail_url(card, page_url, kind)
                        fallback_name = _pick_first_text(card, ["h1", "h2", "h3", ".mansionName", ".property-name", "a"])
                        fallback_address = _pick_first_text(card, [".address", "dd.address"])
                        facts_row = parse_list_card_facts(card, kind, detail_url, fallback_name, fallback_address)

                        if (
                            not facts_row.address
                            or _is_invalid_building_address(facts_row.address)
                            or not _address_has_digits(facts_row.address)
                        ) and detail_url:
                            try:
                                detail_html, from_cache_detail = fetch_html(
                                    session,
                                    detail_url,
                                    cache_dir,
                                    retry_count=retry_count,
                                    sleep_sec=sleep_sec,
                                )
                                if from_cache_detail:
                                    stats["cache_hits"] += 1
                                detail_facts = parse_detail_facts(
                                    detail_html,
                                    detail_url=detail_url,
                                    fallback_name=facts_row.building_name,
                                    fallback_address=facts_row.address,
                                )
                                if (
                                    detail_facts.address
                                    and (
                                        not facts_row.address
                                        or _is_invalid_building_address(facts_row.address)
                                        or (
                                            not _address_has_digits(facts_row.address)
                                            and _address_has_digits(detail_facts.address)
                                        )
                                    )
                                ):
                                    facts_row.address = detail_facts.address
                            except Exception as err:  # noqa: BLE001
                                stats["errors"].append(
                                    {
                                        "kind": kind,
                                        "city_id": city_id,
                                        "page": page,
                                        "url": detail_url,
                                        "error": f"detail fetch failed: {err}",
                                    }
                                )

                        coverage_key = (city_id, kind)
                        counter = facts_coverage.setdefault(
                            coverage_key, {"rows": 0, "address_non_empty": 0, "address_with_digits": 0}
                        )
                        counter["rows"] += 1
                        if facts_row.address:
                            counter["address_non_empty"] += 1
                        if _address_has_digits(facts_row.address):
                            counter["address_with_digits"] += 1
                        all_facts_rows.append(facts_row)

                detail_urls = {row.detail_url for row in rows if row.detail_url}
                same_as_previous = prev_detail_urls is not None and detail_urls == prev_detail_urls
                zero_rows = len(rows) == 0

                if not rows:
                    debug_name = f"{kind}_{city_id}_page{page}.html"
                    debug_path = debug_dir / debug_name
                    debug_path.write_text(page_html, encoding="utf-8")
                    stats["zero_extract_pages"].append(
                        {
                            "kind": kind,
                            "city_id": city_id,
                            "page": page,
                            "url": page_url,
                            "debug_html": str(debug_path.relative_to(out_dir)),
                            "selector_trace": parse_debug.selector_trace,
                            "selector_hits": parse_debug.selector_hits,
                        }
                    )

                print(
                    f"[INFO] kind={kind} city_id={city_id} page={page}/{total_pages} "
                    f"rows={len(rows)} cache_hit={cache_hit_for_log}"
                )

                if max_pages == 0 and not auto_mode:
                    if zero_rows:
                        break
                    if same_as_previous:
                        break

                prev_detail_urls = detail_urls

                next_page = page + 1

                if max_pages > 0:
                    if next_page > total_pages:
                        break
                    next_url = build_city_page_url(kind, city_id, next_page)
                elif auto_mode:
                    if next_page > total_pages:
                        break
                    next_url = build_city_page_url(kind, city_id, next_page)
                else:
                    next_url = find_next_page_url(page_html, page_url, kind, city_id, page)
                    if not next_url:
                        break

                time.sleep(sleep_sec)
                try:
                    next_html, from_cache_page = fetch_html(
                        session,
                        next_url,
                        cache_dir,
                        retry_count=retry_count,
                        sleep_sec=sleep_sec,
                    )
                    if from_cache_page:
                        stats["cache_hits"] += 1
                except Exception as err:  # noqa: BLE001
                    debug_html = _write_fetch_error_debug(debug_dir, out_dir, kind, city_id, next_page, next_url, err)
                    stats["errors"].append(
                        {
                            "kind": kind,
                            "city_id": city_id,
                            "page": next_page,
                            "url": next_url,
                            "error": f"fetch failed: {err}",
                            "debug_html": debug_html,
                        }
                    )
                    break

                page = next_page
                page_url = next_url
                page_html = next_html
                cache_hit_for_log = from_cache_page

                should_continue = True

    stats["rows_total"] = len(all_rows)

    out_csv = out_dir / f"mansion_review_list_{timestamp}.csv"
    facts_csv: Path | None = None

    if mode == "facts":
        facts_map: dict[str, FactsRow] = {}
        for fact in all_facts_rows:
            key = f"{fact.property_kind}|{normalize_space(fact.building_name)}|{normalize_space(fact.address)}"
            if key in facts_map:
                continue
            facts_map[key] = fact

        if not facts_map:
            for row in all_rows:
                key = f"{row.kind}|{normalize_space(row.building_name)}|{_strip_fukuoka_prefix(row.address)}"
                if key in facts_map:
                    continue
                facts_map[key] = FactsRow(
                    building_name=row.building_name,
                    address=_strip_fukuoka_prefix(row.address),
                    structure="RC" if row.kind == "mansion" else "",
                    access_info="",
                    floor_count_text="",
                    total_units=None,
                    management_style="",
                    built_year_month="",
                    property_kind="bunjo" if row.kind == "mansion" else "chintai",
                    sale_price_yen_min=None,
                    sale_price_yen_max=None,
                    sale_price_yen_avg=None,
                    sale_area_sqm_min=None,
                    sale_area_sqm_max=None,
                    sale_layout_types_json="",
                    sale_listing_count=None,
                    avg_rent_yen=None,
                    rental_listing_count=None,
                    availability_label="",
                    evidence_id=f"mansion_review:{normalize_space(row.detail_url) or key}",
                    raw_block="",
                )
        facts_rows = list(facts_map.values())
        combined_dir = out_root / "combined"
        facts_csv = combined_dir / f"building_facts_{timestamp}.csv"
        write_facts_csv(facts_rows, facts_csv)
        stats["facts_total"] = len(facts_rows)
        stats["address_coverage"] = [
            {
                "city_id": city_id,
                "kind": kind,
                "rows": values["rows"],
                "address_non_empty": values["address_non_empty"],
                "address_with_digits": values["address_with_digits"],
            }
            for (city_id, kind), values in sorted(facts_coverage.items())
        ]
    stats_path = out_dir / "stats.json"
    write_csv(all_rows, out_csv)
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    stats["facts_csv"] = str(facts_csv) if facts_csv else None
    return out_dir, facts_csv or out_csv, stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl mansion-review city list pages and export CSV")
    parser.add_argument("--city-ids", default="1616,1619", help="Comma separated city_id values")
    parser.add_argument("--kinds", default="mansion,chintai", help="Comma separated kinds: mansion,chintai")
    parser.add_argument("--mode", default="list", choices=["list", "facts"], help="Crawl mode")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT), help="Output root directory")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE), help="HTML cache directory")
    parser.add_argument("--sleep-sec", type=float, default=0.7, help="Sleep between requests")
    parser.add_argument("--max-pages", type=int, default=0, help="Max pages to crawl (0=auto detect)")
    parser.add_argument("--retry-count", type=int, default=2, help="Retry count on request failures")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="HTTP User-Agent")
    args = parser.parse_args()

    city_ids = parse_csv_arg(args.city_ids)
    kinds = parse_csv_arg(args.kinds)

    if not city_ids:
        raise SystemExit("--city-ids must not be empty")
    if not kinds:
        raise SystemExit("--kinds must not be empty")

    out_dir, out_csv, stats = run_crawl(
        city_ids=city_ids,
        kinds=kinds,
        mode=args.mode,
        out_root=Path(args.out_dir),
        cache_dir=Path(args.cache_dir),
        sleep_sec=args.sleep_sec,
        max_pages=args.max_pages,
        retry_count=args.retry_count,
        user_agent=args.user_agent,
    )

    print(
        f"[OK] pages_total={stats['pages_total']} rows_total={stats['rows_total']} "
        f"zero_extract={len(stats['zero_extract_pages'])} out_csv={out_csv}"
    )
    if stats.get("facts_csv"):
        print(f"[OK] facts_total={stats.get('facts_total', 0)} facts_csv={stats['facts_csv']}")
    print(f"[OK] stats={out_dir / 'stats.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
