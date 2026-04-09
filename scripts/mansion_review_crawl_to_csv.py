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
from typing import Iterable
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
    "repair_fund_text",
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
    "floor_count_text",
    "total_units",
    "evidence_id",
    "raw_block",
)


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
    repair_fund_text: str
    deposit_text: str
    key_money_text: str
    area_text: str
    layout_text: str
    floor_text: str
    direction_text: str


@dataclass
class ParseDebug:
    selector_hits: dict[str, int]
    selector_trace: list[str]


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
        if not m:
            continue
        page = int(m.group(1) or "1")
        max_page = max(max_page, page)
    return max_page


def _extract_building_facts(card: Node) -> dict[str, str]:
    root = card.css_first(".property-detail-content_main")
    if root is None:
        return {}

    facts: dict[str, str] = {}
    for dl in root.css("dl"):
        for dt, dd in zip(dl.css("dt"), dl.css("dd")):
            key = normalize_space(dt.text(separator=" ")).replace("：", "").replace(":", "")
            value = normalize_space(dd.text(separator=" "))
            if key and value:
                facts[key] = value

    for row in root.css("tr"):
        th = row.css_first("th")
        td = row.css_first("td")
        if not th or not td:
            continue
        key = normalize_space(th.text(separator=" ")).replace("：", "").replace(":", "")
        value = normalize_space(td.text(separator=" "))
        if key and value:
            facts[key] = value
    return facts


def _building_fact_value(facts: dict[str, str], labels: Iterable[str]) -> str:
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


def _headers_for_table(table: Node) -> list[str]:
    head_cells = table.css("thead th")
    if not head_cells:
        return []
    return [normalize_space(cell.text(separator=" ")).replace(" ", "") for cell in head_cells]


def _split_rent_and_fee(value: str) -> tuple[str, str]:
    text = normalize_space(value)
    if not text:
        return "", ""
    m = re.match(r"^(.*?)\((.*?)\)$", text)
    if m:
        return normalize_space(m.group(1)), normalize_space(m.group(2))
    if "/" in text:
        left, right = text.split("/", 1)
        return normalize_space(left), normalize_space(right)
    return text, ""


def _value_from_columns(columns: dict[str, str], *keys: str) -> str:
    for key in keys:
        if key in columns:
            return columns[key]
    return ""


def parse_list_page(html: str, page_url: str, kind: str, city_id: str, page_no: int) -> tuple[list[ListRow], ParseDebug]:
    tree = HTMLParser(html)
    cards = tree.css("li.property-detail-list-item, section.property-detail-list-item, article.property-detail-list-item")
    selector_trace = ["li/section/article.property-detail-list-item"]

    if not cards:
        # 最小限の互換: 古い fixture 用。
        cards = tree.css("section.property-card, article.property-card")
        selector_trace.append("section/article.property-card")

    rows: list[ListRow] = []
    for card in cards:
        facts = _extract_building_facts(card)
        building_name = normalize_space(
            (card.css_first("h1, h2, h3, .property-name, .mansionName") or card).text(separator=" ")
        )
        address = _building_fact_value(facts, ("住所", "所在地"))
        access_text = _building_fact_value(facts, ("交通", "アクセス"))
        built_text = _building_fact_value(facts, ("築年数", "築年月", "築"))
        building_floor_count_text = _building_fact_value(facts, ("階建て", "建物階数"))
        total_units_text = _building_fact_value(facts, ("総戸数",))
        detail_url = _extract_detail_url(card, page_url, kind)

        recommend_table = card.css_first("table.recommendTable")
        if recommend_table is None:
            continue

        headers = _headers_for_table(recommend_table)
        recommend_rows = recommend_table.css("tbody.recommend_row tr")
        for tr in recommend_rows:
            cells = [normalize_space(td.text(separator=" ")) for td in tr.css("td")]
            if not cells:
                continue
            columns = {headers[idx]: cells[idx] for idx in range(min(len(headers), len(cells)))} if headers else {}

            if kind == "chintai":
                rent_or_combined = _value_from_columns(columns, "賃料(管理費)", "賃料", "賃料/管理費") or (cells[0] if cells else "")
                rent_text, fee_inline = _split_rent_and_fee(rent_or_combined)
                fee_text = _value_from_columns(columns, "管理費", "共益費") or fee_inline
                row = ListRow(
                    kind=kind,
                    city_id=city_id,
                    ward=CITY_MAP.get(city_id, ""),
                    city_page=f"{city_id}_{page_no}",
                    page_url=page_url,
                    detail_url=detail_url,
                    building_name=building_name,
                    address=address,
                    access_text=access_text,
                    built_text=built_text,
                    building_floor_count_text=building_floor_count_text,
                    total_units_text=total_units_text,
                    price_or_rent_text=rent_text,
                    fee_text=fee_text,
                    repair_fund_text="",
                    deposit_text=_value_from_columns(columns, "敷金"),
                    key_money_text=_value_from_columns(columns, "礼金"),
                    area_text=_value_from_columns(columns, "専有面積", "面積"),
                    layout_text=_value_from_columns(columns, "間取り"),
                    floor_text=_value_from_columns(columns, "所在階", "階"),
                    direction_text=_value_from_columns(columns, "向き", "主要採光面"),
                )
            else:
                row = ListRow(
                    kind=kind,
                    city_id=city_id,
                    ward=CITY_MAP.get(city_id, ""),
                    city_page=f"{city_id}_{page_no}",
                    page_url=page_url,
                    detail_url=detail_url,
                    building_name=building_name,
                    address=address,
                    access_text=access_text,
                    built_text=built_text,
                    building_floor_count_text=building_floor_count_text,
                    total_units_text=total_units_text,
                    price_or_rent_text=_value_from_columns(columns, "価格", "販売価格") or (cells[0] if cells else ""),
                    fee_text=_value_from_columns(columns, "管理費"),
                    repair_fund_text=_value_from_columns(columns, "修繕積立金"),
                    deposit_text="",
                    key_money_text="",
                    area_text=_value_from_columns(columns, "専有面積", "面積"),
                    layout_text=_value_from_columns(columns, "間取り"),
                    floor_text=_value_from_columns(columns, "所在階", "階"),
                    direction_text=_value_from_columns(columns, "向き", "主要採光面"),
                )
            rows.append(row)

    return rows, ParseDebug(selector_hits={"cards": len(cards), "rows": len(rows)}, selector_trace=selector_trace)


def _cache_path(cache_dir: Path, url: str) -> Path:
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{key}.html"


def fetch_html(session: requests.Session, url: str, cache_dir: Path, *, retry_count: int, sleep_sec: float) -> tuple[str, bool]:
    cache_file = _cache_path(cache_dir, url)
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8"), True

    last_error: Exception | None = None
    for attempt in range(retry_count + 1):
        try:
            response = session.get(url, timeout=20)
            response.raise_for_status()
            response.encoding = response.encoding or "utf-8"
            html = response.text
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(html, encoding="utf-8")
            return html, False
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


def _facts_rows_from_list_rows(rows: list[ListRow]) -> list[dict[str, str]]:
    result: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (row.kind, f"{row.building_name}|{row.address}")
        if key in result:
            continue
        raw_block = " | ".join(
            [
                f"交通:{row.access_text}",
                f"築年数:{row.built_text}",
                f"階建て:{row.building_floor_count_text}",
                f"総戸数:{row.total_units_text}",
                f"詳細URL:{row.detail_url}",
            ]
        )
        evidence_source = row.detail_url or f"{row.kind}:{row.building_name}:{row.address}"
        result[key] = {
            "building_name": row.building_name,
            "address": row.address,
            "access_info": row.access_text,
            "floor_count_text": row.building_floor_count_text,
            "total_units": _parse_total_units(row.total_units_text),
            "evidence_id": f"mansion_review:{evidence_source}",
            "raw_block": raw_block,
        }
    return list(result.values())


def _write_facts_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(FACTS_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def run_crawl(
    *,
    city_ids: list[str],
    kinds: list[str],
    mode: str,
    out_root: Path,
    cache_dir: Path,
    sleep_sec: float,
    max_pages: int,
    retry_count: int,
    user_agent: str,
) -> tuple[Path, Path, dict[str, object]]:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_dir = out_root / timestamp
    all_rows: list[ListRow] = []
    stats: dict[str, object] = {"pages_total": 0, "rows_total": 0, "errors": []}

    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})

    for kind in kinds:
        for city_id in city_ids:
            page1_url = build_city_page_url(kind, city_id, 1)
            try:
                page1_html, _ = fetch_html(
                    session,
                    page1_url,
                    cache_dir,
                    retry_count=retry_count,
                    sleep_sec=sleep_sec,
                )
            except Exception as err:  # noqa: BLE001
                stats["errors"].append({"kind": kind, "city_id": city_id, "page": 1, "url": page1_url, "error": str(err)})
                continue

            total_pages = parse_max_page(page1_html, kind=kind, city_id=city_id)
            if max_pages > 0:
                total_pages = min(total_pages, max_pages)

            for page_no in range(1, total_pages + 1):
                page_url = build_city_page_url(kind, city_id, page_no)
                try:
                    html, _ = (page1_html, True) if page_no == 1 else fetch_html(
                        session,
                        page_url,
                        cache_dir,
                        retry_count=retry_count,
                        sleep_sec=sleep_sec,
                    )
                    rows, _ = parse_list_page(html, page_url, kind, city_id, page_no)
                    all_rows.extend(rows)
                    stats["pages_total"] = int(stats["pages_total"]) + 1
                except Exception as err:  # noqa: BLE001
                    stats["errors"].append(
                        {"kind": kind, "city_id": city_id, "page": page_no, "url": page_url, "error": str(err)}
                    )
                time.sleep(sleep_sec)

    list_csv = run_dir / f"mansion_review_list_{timestamp}.csv"
    _write_list_csv(all_rows, list_csv)
    stats["rows_total"] = len(all_rows)

    if mode == "facts":
        facts_rows = _facts_rows_from_list_rows(all_rows)
        facts_csv = out_root / "combined" / f"building_facts_{timestamp}.csv"
        _write_facts_csv(facts_rows, facts_csv)
        stats["facts_total"] = len(facts_rows)
        out_csv = facts_csv
    else:
        out_csv = list_csv

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    return run_dir, out_csv, stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl mansion-review city list pages and export CSV")
    parser.add_argument("--city-ids", default="1616,1619")
    parser.add_argument("--kinds", default="mansion,chintai")
    parser.add_argument("--mode", default="list", choices=["list", "facts"])
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    parser.add_argument("--sleep-sec", type=float, default=0.7)
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--retry-count", type=int, default=2)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    args = parser.parse_args()

    city_ids = parse_csv_arg(args.city_ids)
    kinds = parse_csv_arg(args.kinds)
    if not city_ids or not kinds:
        raise SystemExit("--city-ids/--kinds must not be empty")

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
        f"errors={len(stats['errors'])} out_csv={out_csv}"
    )
    print(f"[OK] stats={out_dir / 'stats.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
