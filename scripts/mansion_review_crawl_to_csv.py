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
from typing import Any
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


@dataclass
class ParseDebug:
    selector_hits: dict[str, int]
    selector_trace: list[str]


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_csv_arg(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_city_page_url(kind: str, city_id: str, page: int) -> str:
    suffix = "" if page == 1 else f"_{page}"
    return f"{BASE_URL}/{kind}/city/{city_id}{suffix}.html"


def _pick_first_text(node: Node, selectors: list[str]) -> str:
    for selector in selectors:
        picked = node.css_first(selector)
        if picked:
            txt = normalize_space(picked.text(separator=" "))
            if txt:
                return txt
    return ""


def _find_detail_url(card: Node, base_url: str, kind: str) -> str:
    candidates = [
        f'a[href*="/{kind}/"]',
        'a[href*="/mansion/"]',
        'a[href*="/chintai/"]',
        "a[href]",
    ]
    for selector in candidates:
        for anchor in card.css(selector):
            href = normalize_space(anchor.attributes.get("href", ""))
            if not href:
                continue
            if href.startswith("javascript:"):
                continue
            return urljoin(base_url, href)
    return ""


def _find_text_with_pattern(card: Node, patterns: list[str]) -> str:
    text = normalize_space(card.text(separator=" "))
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return normalize_space(match.group(0))
    return ""


def detect_card_nodes(tree: HTMLParser) -> tuple[list[Node], ParseDebug]:
    selectors = [
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
        address = _pick_first_text(card, [".address", "dd.address", "dd", "[class*='address']"])
        if not address:
            address = _find_text_with_pattern(card, [r"(?:福岡県)?北九州市[^\s]{0,20}区[^\s]{0,120}"])

        price_or_rent_text = _pick_first_text(
            card,
            [
                ".price",
                ".rent",
                ".money",
                "td",
                "dd",
                "span",
            ],
        )
        if not price_or_rent_text:
            price_or_rent_text = _find_text_with_pattern(card, [r"\d[\d,]*(?:\.\d+)?\s*(?:万円|円)"])

        layout_text = _pick_first_text(card, [".layout", "[class*='layout']", "td", "dd"])
        if not re.search(r"\d\s*[SLDKR]", layout_text):
            layout_text = _find_text_with_pattern(card, [r"\d\s*[SLDKR]+"])

        area_text = _pick_first_text(card, [".area", "[class*='area']", "td", "dd"])
        if not re.search(r"(?:㎡|m²|m2)", area_text):
            area_text = _find_text_with_pattern(card, [r"\d+(?:\.\d+)?\s*(?:㎡|m²|m2)"])

        floor_text = _pick_first_text(card, [".floor", "[class*='floor']", "td", "dd"])
        if not re.search(r"(?:階|F)", floor_text):
            floor_text = _find_text_with_pattern(card, [r"(?:\d+階|\d+F|地上\d+階|地下\d+階)"])

        detail_url = _find_detail_url(card, page_url, kind)

        if not building_name:
            continue

        rows.append(
            ListRow(
                kind=kind,
                city_id=city_id,
                ward=CITY_MAP.get(city_id, ""),
                city_page=f"{city_id}_{page_no}",
                page_url=page_url,
                building_name=building_name,
                address=address,
                detail_url=detail_url,
                price_or_rent_text=price_or_rent_text,
                layout_text=layout_text,
                area_text=area_text,
                floor_text=floor_text,
            )
        )

    return rows, debug


def parse_max_page(html: str) -> int:
    tree = HTMLParser(html)
    max_page = 1
    for node in tree.css("a[href], span, li"):
        txt = normalize_space(node.text(separator=" "))
        if txt.isdigit():
            max_page = max(max_page, int(txt))
    for href_node in tree.css("a[href]"):
        href = href_node.attributes.get("href") or ""
        if not href:
            continue
        m = re.search(r"_(\d+)\.html", href)
        if m:
            max_page = max(max_page, int(m.group(1)))
    return max_page


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
) -> tuple[Path, Path, dict[str, Any]]:
    if mode != "list":
        raise ValueError(f"Unsupported mode: {mode}. Only mode=list is currently implemented.")

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
            else:
                detected_pages = parse_max_page(html)
                total_pages = max(detected_pages, 1)

            for page in range(1, total_pages + 1):
                page_url = build_city_page_url(kind, city_id, page)
                if page == 1:
                    page_html = html
                else:
                    time.sleep(sleep_sec)
                    try:
                        page_html, from_cache_page = fetch_html(
                            session,
                            page_url,
                            cache_dir,
                            retry_count=retry_count,
                            sleep_sec=sleep_sec,
                        )
                        if from_cache_page:
                            stats["cache_hits"] += 1
                    except Exception as err:  # noqa: BLE001
                        debug_html = _write_fetch_error_debug(debug_dir, out_dir, kind, city_id, page, page_url, err)
                        stats["errors"].append(
                            {
                                "kind": kind,
                                "city_id": city_id,
                                "page": page,
                                "url": page_url,
                                "error": f"fetch failed: {err}",
                                "debug_html": debug_html,
                            }
                        )
                        continue

                rows, parse_debug = parse_list_page(page_html, page_url, kind, city_id, page)
                stats["pages_total"] += 1
                all_rows.extend(rows)

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
                    f"rows={len(rows)} cache_hit={from_cache if page == 1 else from_cache_page}"
                )

                time.sleep(sleep_sec)

    stats["rows_total"] = len(all_rows)

    out_csv = out_dir / f"mansion_review_list_{timestamp}.csv"
    stats_path = out_dir / "stats.json"
    write_csv(all_rows, out_csv)
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    return out_dir, out_csv, stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl mansion-review city list pages and export CSV")
    parser.add_argument("--city-ids", default="1616,1619", help="Comma separated city_id values")
    parser.add_argument("--kinds", default="mansion,chintai", help="Comma separated kinds: mansion,chintai")
    parser.add_argument("--mode", default="list", choices=["list", "detail"], help="Crawl mode (detail reserved)")
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
    print(f"[OK] stats={out_dir / 'stats.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
