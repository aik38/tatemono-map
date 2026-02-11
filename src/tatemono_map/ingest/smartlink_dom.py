from __future__ import annotations

import argparse
import hashlib
import json
import os
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from selectolax.parser import HTMLParser

from tatemono_map.db.repo import ListingRecord, connect
from tatemono_map.ingest.ulucks_playwright import _extract_pagination_hrefs
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.util.area import parse_area_sqm
from tatemono_map.util.money import parse_rent_yen
from tatemono_map.util.text import normalize_text

_HEADER_HINTS = ("家賃", "万円", "間取り", "㎡", "物件", "空室", "所在地", "更新")
_TABLE_SCOPED_SELECTORS = (
    "table",
    "#search_list table",
    "#search_result table",
    "#search_list_result table",
)


@dataclass(frozen=True)
class _ColumnMap:
    name_idx: int | None = None
    room_idx: int | None = None
    rent_idx: int | None = None
    maint_idx: int | None = None
    area_idx: int | None = None
    layout_idx: int | None = None
    address_idx: int | None = None
    move_in_idx: int | None = None
    updated_idx: int | None = None
    detail_idx: int | None = None


@dataclass(frozen=True)
class _DebugPageSnapshot:
    url: str
    title: str
    html: str


def _sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _building_key(name: str, address: str) -> str:
    return _sha1(f"{normalize_text(address)}|{normalize_text(name)}")


def _listing_key(source_url: str, name: str, address: str, layout: str | None, area_sqm: float | None, rent_yen: int | None) -> str:
    return _sha1(
        "|".join(
            [
                normalize_text(source_url),
                normalize_text(name),
                normalize_text(address),
                normalize_text(layout or ""),
                str(area_sqm or ""),
                str(rent_yen or ""),
            ]
        )
    )


def _to_absolute_href(current_url: str, href: str | None) -> str | None:
    if not href:
        return None
    value = href.strip()
    if not value:
        return None
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("//"):
        if current_url.startswith("https://"):
            return f"https:{value}"
        if current_url.startswith("http://"):
            return f"http:{value}"
        return None
    if value.startswith("/"):
        prefix = current_url.split("/", 3)
        if len(prefix) < 3:
            return None
        return f"{prefix[0]}//{prefix[2]}{value}"
    if current_url.endswith("/"):
        return f"{current_url}{value}"
    parent = current_url.rsplit("/", 1)
    if len(parent) != 2:
        return None
    return f"{parent[0]}/{value}"


def _score_table(table) -> int:
    header_texts: list[str] = []
    for row in table.css("tr")[:5]:
        for cell in row.css("th, td"):
            header_texts.append(normalize_text(cell.text()))
    if not header_texts:
        return 0

    score = 0
    for hint in _HEADER_HINTS:
        if any(hint in text for text in header_texts):
            score += 3
    if any("所在地" in text for text in header_texts):
        score += 4
    if any("検索結果" in text for text in header_texts):
        score += 1
    if any("空室" in text for text in header_texts):
        score += 2
    return score


def _candidate_tables(html: str) -> list[Any]:
    tree = HTMLParser(html)
    tables: list[Any] = []
    seen_ids: set[int] = set()
    for selector in _TABLE_SCOPED_SELECTORS:
        for table in tree.css(selector):
            table_id = id(table)
            if table_id in seen_ids:
                continue
            seen_ids.add(table_id)
            tables.append(table)
    return tables


def _column_map(header_cells: list[str]) -> _ColumnMap:
    name_idx = room_idx = rent_idx = maint_idx = area_idx = layout_idx = address_idx = move_in_idx = updated_idx = detail_idx = None
    for idx, label in enumerate(header_cells):
        text = normalize_text(label)
        if ("物件" in text or "建物" in text or "物件名" in text) and name_idx is None:
            name_idx = idx
        if ("号室" in text or "部屋" in text) and room_idx is None:
            room_idx = idx
        if ("賃料" in text or "家賃" in text or "万円" in text) and rent_idx is None:
            rent_idx = idx
        if ("管理費" in text or "共益費" in text) and maint_idx is None:
            maint_idx = idx
        if ("間取" in text or "間取り" in text) and layout_idx is None:
            layout_idx = idx
        if ("㎡" in text or "m2" in text.lower() or "面積" in text) and area_idx is None:
            area_idx = idx
        if "所在" in text and address_idx is None:
            address_idx = idx
        if "入居" in text and move_in_idx is None:
            move_in_idx = idx
        if ("更新" in text or "掲載" in text) and updated_idx is None:
            updated_idx = idx
        if ("詳細" in text or "内見" in text) and detail_idx is None:
            detail_idx = idx
    return _ColumnMap(
        name_idx=name_idx,
        room_idx=room_idx,
        rent_idx=rent_idx,
        maint_idx=maint_idx,
        area_idx=area_idx,
        layout_idx=layout_idx,
        address_idx=address_idx,
        move_in_idx=move_in_idx,
        updated_idx=updated_idx,
        detail_idx=detail_idx,
    )


def _find_header_row(rows: list[Any]) -> tuple[int | None, list[str]]:
    for idx, row in enumerate(rows):
        cells = row.css("th, td")
        labels = [normalize_text(cell.text()) for cell in cells]
        if labels and any(any(h in label for h in _HEADER_HINTS) for label in labels):
            return idx, labels
    return None, []


def _extract_rows_from_table(source_url: str, table) -> list[ListingRecord]:
    rows = table.css("tr")
    header_row_idx, headers = _find_header_row(rows)
    if header_row_idx is None:
        return []

    mapping = _column_map(headers)
    records: list[ListingRecord] = []
    for row in rows[header_row_idx + 1 :]:
        cells = row.css("td")
        if not cells:
            continue
        texts = [normalize_text(cell.text(deep=True, separator=" ")) for cell in cells]
        if not any(texts):
            continue

        name = texts[mapping.name_idx] if mapping.name_idx is not None and mapping.name_idx < len(texts) else ""
        room_name = texts[mapping.room_idx] if mapping.room_idx is not None and mapping.room_idx < len(texts) else ""
        address = texts[mapping.address_idx] if mapping.address_idx is not None and mapping.address_idx < len(texts) else ""
        layout = texts[mapping.layout_idx] if mapping.layout_idx is not None and mapping.layout_idx < len(texts) else ""
        area_raw = texts[mapping.area_idx] if mapping.area_idx is not None and mapping.area_idx < len(texts) else ""
        rent_raw = texts[mapping.rent_idx] if mapping.rent_idx is not None and mapping.rent_idx < len(texts) else ""
        maint_raw = texts[mapping.maint_idx] if mapping.maint_idx is not None and mapping.maint_idx < len(texts) else ""
        move_in = texts[mapping.move_in_idx] if mapping.move_in_idx is not None and mapping.move_in_idx < len(texts) else ""
        updated = texts[mapping.updated_idx] if mapping.updated_idx is not None and mapping.updated_idx < len(texts) else ""

        detail_url = None
        if mapping.detail_idx is not None and mapping.detail_idx < len(cells):
            detail_url = _to_absolute_href(source_url, cells[mapping.detail_idx].attributes.get("href"))
        if not detail_url:
            anchor = row.css_first("a[href]")
            if anchor is not None:
                detail_url = _to_absolute_href(source_url, anchor.attributes.get("href"))

        if not name or not address:
            continue

        rent_yen = parse_rent_yen(rent_raw)
        maint_yen = parse_rent_yen(maint_raw)
        area_sqm = parse_area_sqm(area_raw)
        source_value = detail_url or source_url
        records.append(
            ListingRecord(
                name=name,
                address=address,
                room_label=room_name or None,
                rent_yen=rent_yen,
                maint_yen=maint_yen,
                layout=layout or None,
                area_sqm=area_sqm,
                move_in_date=move_in or None,
                updated_at=updated or None,
                source_kind="smartlink_dom",
                source_url=source_value,
            )
        )
    return records


def _extract_kv_card_from_table(source_url: str, table) -> list[ListingRecord]:
    rows = table.css("tr")
    fields: dict[str, str] = {}
    for row in rows:
        cells = row.css("th, td")
        if len(cells) < 2:
            continue
        key = normalize_text(cells[0].text(deep=True, separator=" "))
        value = normalize_text(cells[1].text(deep=True, separator=" "))
        if not key or not value:
            continue
        fields[key] = value

    name = fields.get("物件名/号室") or fields.get("物件名") or fields.get("建物名") or ""
    address = fields.get("所在地") or ""
    if not name or not address:
        return []

    detail_url = None
    anchor = table.css_first("a[href]")
    if anchor is not None:
        detail_url = _to_absolute_href(source_url, anchor.attributes.get("href"))

    return [
        ListingRecord(
            name=name,
            address=address,
            room_label=fields.get("号室") or None,
            rent_yen=parse_rent_yen(fields.get("家賃") or fields.get("賃料") or ""),
            maint_yen=parse_rent_yen(fields.get("管理費") or fields.get("共益費") or ""),
            layout=fields.get("間取り") or fields.get("間取") or None,
            area_sqm=parse_area_sqm(fields.get("専有面積") or fields.get("面積") or ""),
            move_in_date=fields.get("入居可能日") or fields.get("入居") or None,
            updated_at=fields.get("更新日時") or fields.get("更新日") or None,
            source_kind="smartlink_dom",
            source_url=detail_url or source_url,
        )
    ]


def extract_records(source_url: str, html: str) -> list[ListingRecord]:
    scored: list[tuple[int, Any]] = [(_score_table(table), table) for table in _candidate_tables(html)]
    scored = sorted(scored, key=lambda item: item[0], reverse=True)

    seen: set[str] = set()
    records: list[ListingRecord] = []
    for score, table in scored:
        if score <= 0:
            continue
        table_records = _extract_rows_from_table(source_url=source_url, table=table)
        if not table_records:
            table_records = _extract_kv_card_from_table(source_url=source_url, table=table)
        for record in table_records:
            rec_key = _listing_key(record.source_url, record.name, record.address, record.layout, record.area_sqm, record.rent_yen)
            if rec_key in seen:
                continue
            seen.add(rec_key)
            records.append(record)
    return records


def _collect_parse_debug_meta(source_url: str, html: str) -> dict[str, int | str]:
    tables = _candidate_tables(html)
    positive_scored = sum(1 for table in tables if _score_table(table) > 0)
    tree = HTMLParser(html)
    return {
        "source_url": source_url,
        "found_tables": len(tables),
        "found_positive_scored_tables": positive_scored,
        "found_update_labels": len(tree.css("*:contains('更新日時')")),
        "found_name_labels": len(tree.css("*:contains('物件名')")),
        "found_address_labels": len(tree.css("*:contains('所在地')")),
        "found_rent_labels": len(tree.css("*:contains('家賃')")),
        "found_pagination_links": len(tree.css("a[href*='/view/smartlink/page:']")),
    }


def _bulk_upsert(db_path: str, records: list[ListingRecord]) -> int:
    conn = connect(db_path)
    payload = []
    for record in records:
        building_key = _building_key(record.name, record.address)
        listing_key = _listing_key(
            source_url=record.source_url,
            name=record.name,
            address=record.address,
            layout=record.layout,
            area_sqm=record.area_sqm,
            rent_yen=record.rent_yen,
        )
        payload.append(
            (
                listing_key,
                building_key,
                record.name,
                record.address,
                record.room_label,
                record.rent_yen,
                record.maint_yen,
                record.layout,
                record.area_sqm,
                record.move_in_date,
                record.updated_at,
                record.source_kind,
                record.source_url,
                record.management_company,
                record.management_phone,
            )
        )

    if not payload:
        conn.close()
        return 0

    conn.executemany(
        """
        INSERT INTO listings(
            listing_key, building_key, name, address, room_label,
            rent_yen, maint_yen, layout, area_sqm, move_in_date,
            updated_at, source_kind, source_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(listing_key) DO UPDATE SET
            building_key=excluded.building_key,
            name=excluded.name,
            address=excluded.address,
            room_label=excluded.room_label,
            rent_yen=excluded.rent_yen,
            maint_yen=excluded.maint_yen,
            layout=excluded.layout,
            area_sqm=excluded.area_sqm,
            move_in_date=excluded.move_in_date,
            updated_at=excluded.updated_at,
            source_kind=excluded.source_kind,
            source_url=excluded.source_url
        """,
        [row[:-2] for row in payload],
    )

    conn.executemany(
        """
        INSERT INTO raw_units(
            listing_key, building_key, name, address, room_label,
            rent_yen, maint_yen, layout, area_sqm, move_in_date,
            updated_at, source_kind, source_url, management_company, management_phone
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(listing_key) DO UPDATE SET
            building_key=excluded.building_key,
            name=excluded.name,
            address=excluded.address,
            room_label=excluded.room_label,
            rent_yen=excluded.rent_yen,
            maint_yen=excluded.maint_yen,
            layout=excluded.layout,
            area_sqm=excluded.area_sqm,
            move_in_date=excluded.move_in_date,
            updated_at=excluded.updated_at,
            source_kind=excluded.source_kind,
            source_url=excluded.source_url,
            management_company=excluded.management_company,
            management_phone=excluded.management_phone
        """,
        payload,
    )
    conn.commit()
    conn.close()
    return len(payload)


def persist_records(db_path: str, records: list[ListingRecord]) -> tuple[int, int]:
    if not records:
        raise RuntimeError("smartlink_dom ingest produced 0 records")
    upserted = _bulk_upsert(db_path=db_path, records=records)
    summary_count = rebuild(db_path)
    return upserted, summary_count


def _safe_slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)[:64] or "untitled"


def _snapshot_page(page) -> _DebugPageSnapshot:
    return _DebugPageSnapshot(url=page.url, title=page.title(), html=page.content())


def _dump_debug(
    debug_dir: Path | None,
    page,
    page_index: int,
    stage: str,
    reason: str | None = None,
    extra_meta: dict[str, Any] | None = None,
    error_text: str | None = None,
) -> Path | None:
    if debug_dir is None:
        return None
    snapshot = _snapshot_page(page)
    page_dir = debug_dir / f"{page_index:03d}_{_safe_slug(stage)}"
    page_dir.mkdir(parents=True, exist_ok=True)
    png_path = page_dir / "page.png"
    html_path = page_dir / "page.html"
    meta_path = page_dir / "meta.json"

    page.screenshot(path=str(png_path), full_page=True)
    html_path.write_text(snapshot.html, encoding="utf-8")
    meta = {
        "captured_at": datetime.now().isoformat(),
        "stage": stage,
        "reason": reason,
        "url": snapshot.url,
        "title": snapshot.title,
        "page_index": page_index,
    }
    if extra_meta:
        meta.update(extra_meta)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    if error_text:
        (page_dir / "error.txt").write_text(error_text, encoding="utf-8")
    return page_dir


def _prepare_debug_root(debug_dir: str | None) -> Path | None:
    if not debug_dir:
        return None
    root = Path(debug_dir)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = root / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _wait_for_listing_dom(page, timeout_ms: int = 20_000) -> None:
    markers = [
        "text=空室一覧",
        "text=検索結果",
        "a[href*='/view/smartlink/page:']",
        "table:has-text('家賃')",
        "table:has-text('所在地')",
    ]
    for marker in markers:
        try:
            page.locator(marker).first.wait_for(state="visible", timeout=timeout_ms)
            return
        except Exception:
            continue
    raise RuntimeError("listing DOM markers did not appear")


def _navigate_to_listing(page, url: str, sleep_ms: int = 800) -> None:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    try:
        page.goto(url, wait_until="networkidle", timeout=45_000)
    except PlaywrightTimeoutError:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)

    page.locator("body").first.wait_for(state="visible", timeout=15_000)
    for _ in range(6):
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(180)

    toggle_selectors = [
        "#search_list_header button",
        "#search_list_header img",
        "button:has-text('表示')",
        "button:has-text('検索結果')",
    ]
    for selector in toggle_selectors:
        try:
            target = page.locator(selector).first
            if target.count() > 0 and target.is_visible():
                target.click(timeout=1_500)
                page.wait_for_timeout(300)
        except Exception:
            continue

    _wait_for_listing_dom(page)
    if sleep_ms > 0:
        page.wait_for_timeout(sleep_ms)


def ingest(
    start_url: str,
    db_path: str,
    max_pages: int = 20,
    sleep_ms: int = 800,
    debug_dir: str | None = None,
    headless: bool | None = None,
) -> tuple[int, int]:
    from playwright.sync_api import sync_playwright

    all_records: list[ListingRecord] = []
    queue: deque[str] = deque([start_url])
    visited: set[str] = set()
    debug_root = _prepare_debug_root(debug_dir)

    if headless is None:
        env_headless = os.getenv("SMARTLINK_HEADLESS")
        headless = False if env_headless is None else env_headless.lower() not in {"0", "false", "no"}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 2200},
            locale="ja-JP",
        )
        page = context.new_page()

        while queue and len(visited) < max_pages:
            url = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            try:
                _navigate_to_listing(page=page, url=url, sleep_ms=sleep_ms)
                _dump_debug(debug_root, page, len(visited), "before_parse")
                current_url = page.url
                html = page.content()
                page_records = extract_records(current_url, html)
                if not page_records:
                    _dump_debug(
                        debug_root,
                        page,
                        len(visited),
                        "parse_failed",
                        reason="0 records on page",
                        extra_meta=_collect_parse_debug_meta(current_url, html),
                    )
                all_records.extend(page_records)
                for href in _extract_pagination_hrefs(current_url, html):
                    if href not in visited:
                        queue.append(href)
            except Exception as exc:
                _dump_debug(
                    debug_root,
                    page,
                    len(visited),
                    "parse_failed",
                    reason=str(exc),
                    error_text=traceback.format_exc(),
                )
                raise

        context.close()
        browser.close()

    if not all_records:
        raise RuntimeError(f"smartlink_dom ingest produced 0 records (debug_dir={debug_root})")
    return persist_records(db_path=db_path, records=all_records)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", "--db-path", dest="db_path", default="data/tatemono_map.sqlite3")
    parser.add_argument("--start-url", required=True)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--sleep-ms", type=int, default=800)
    parser.add_argument("--debug-dir", default=None)
    parser.add_argument("--headless", dest="headless", action="store_true")
    parser.add_argument("--headed", dest="headless", action="store_false")
    parser.set_defaults(headless=None)
    args = parser.parse_args()

    upserted, summary_count = ingest(
        start_url=args.start_url,
        db_path=args.db_path,
        max_pages=args.max_pages,
        sleep_ms=args.sleep_ms,
        debug_dir=args.debug_dir,
        headless=args.headless,
    )
    print(f"upserted raw_units/listings: {upserted}")
    print(f"rebuilt building_summaries: {summary_count}")


if __name__ == "__main__":
    main()
