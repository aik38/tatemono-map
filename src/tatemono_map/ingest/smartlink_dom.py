from __future__ import annotations

import argparse
import hashlib
from collections import deque
from dataclasses import dataclass

from selectolax.parser import HTMLParser

from tatemono_map.db.repo import ListingRecord, connect
from tatemono_map.ingest.ulucks_playwright import _extract_pagination_hrefs
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.util.area import parse_area_sqm
from tatemono_map.util.money import parse_rent_yen
from tatemono_map.util.text import normalize_text

_HEADER_HINTS = ("家賃", "万円", "間取り", "㎡", "物件", "空室")


@dataclass(frozen=True)
class _ColumnMap:
    name_idx: int | None = None
    rent_idx: int | None = None
    maint_idx: int | None = None
    area_idx: int | None = None
    layout_idx: int | None = None
    address_idx: int | None = None
    move_in_idx: int | None = None
    updated_idx: int | None = None


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


def _score_table(table) -> int:
    header_texts: list[str] = []
    for row in table.css("tr")[:4]:
        for cell in row.css("th, td"):
            header_texts.append(normalize_text(cell.text()))
    if not header_texts:
        return 0
    score = 0
    for hint in _HEADER_HINTS:
        if any(hint in text for text in header_texts):
            score += 3
    if any("所在地" in text for text in header_texts):
        score += 2
    if any("入居" in text for text in header_texts):
        score += 1
    return score


def _best_table(html: str):
    tree = HTMLParser(html)
    tables = tree.css("table")
    if not tables:
        return None
    scored = sorted(((table, _score_table(table)) for table in tables), key=lambda item: item[1], reverse=True)
    best, score = scored[0]
    if score <= 0:
        return None
    return best


def _column_map(header_cells: list[str]) -> _ColumnMap:
    name_idx = rent_idx = maint_idx = area_idx = layout_idx = address_idx = move_in_idx = updated_idx = None
    for idx, label in enumerate(header_cells):
        text = normalize_text(label)
        if ("物件" in text or "建物" in text) and name_idx is None:
            name_idx = idx
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
    return _ColumnMap(
        name_idx=name_idx,
        rent_idx=rent_idx,
        maint_idx=maint_idx,
        area_idx=area_idx,
        layout_idx=layout_idx,
        address_idx=address_idx,
        move_in_idx=move_in_idx,
        updated_idx=updated_idx,
    )


def _extract_rows_from_table(source_url: str, table) -> list[ListingRecord]:
    rows = table.css("tr")
    header_row_idx = None
    headers: list[str] = []
    for idx, row in enumerate(rows):
        header_cells = [normalize_text(cell.text()) for cell in row.css("th")]
        if header_cells and any(any(h in label for h in _HEADER_HINTS) for label in header_cells):
            header_row_idx = idx
            headers = header_cells
            break

    if header_row_idx is None:
        return []

    mapping = _column_map(headers)
    records: list[ListingRecord] = []
    for row in rows[header_row_idx + 1 :]:
        cells = [normalize_text(cell.text(deep=True, separator=" ")) for cell in row.css("td")]
        if not cells:
            continue

        name = cells[mapping.name_idx] if mapping.name_idx is not None and mapping.name_idx < len(cells) else ""
        address = cells[mapping.address_idx] if mapping.address_idx is not None and mapping.address_idx < len(cells) else ""
        layout = cells[mapping.layout_idx] if mapping.layout_idx is not None and mapping.layout_idx < len(cells) else ""
        area_raw = cells[mapping.area_idx] if mapping.area_idx is not None and mapping.area_idx < len(cells) else ""
        rent_raw = cells[mapping.rent_idx] if mapping.rent_idx is not None and mapping.rent_idx < len(cells) else ""
        maint_raw = cells[mapping.maint_idx] if mapping.maint_idx is not None and mapping.maint_idx < len(cells) else ""
        move_in = cells[mapping.move_in_idx] if mapping.move_in_idx is not None and mapping.move_in_idx < len(cells) else ""
        updated = cells[mapping.updated_idx] if mapping.updated_idx is not None and mapping.updated_idx < len(cells) else ""

        if not name or not address:
            continue

        rent_yen = parse_rent_yen(rent_raw)
        maint_yen = parse_rent_yen(maint_raw)
        area_sqm = parse_area_sqm(area_raw)
        records.append(
            ListingRecord(
                name=name,
                address=address,
                room_label=None,
                rent_yen=rent_yen,
                maint_yen=maint_yen,
                layout=layout or None,
                area_sqm=area_sqm,
                move_in_date=move_in or None,
                updated_at=updated or None,
                source_kind="smartlink_dom",
                source_url=source_url,
            )
        )
    return records


def extract_records(source_url: str, html: str) -> list[ListingRecord]:
    table = _best_table(html)
    if table is None:
        return []
    return _extract_rows_from_table(source_url=source_url, table=table)


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


def ingest(start_url: str, db_path: str, max_pages: int = 20, sleep_ms: int = 800) -> tuple[int, int]:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    all_records: list[ListingRecord] = []
    queue: deque[str] = deque([start_url])
    visited: set[str] = set()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        while queue and len(visited) < max_pages:
            url = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            try:
                page.goto(url, wait_until="networkidle", timeout=45_000)
            except PlaywrightTimeoutError:
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            if sleep_ms > 0:
                page.wait_for_timeout(sleep_ms)

            current_url = page.url
            html = page.content()
            all_records.extend(extract_records(current_url, html))
            for href in _extract_pagination_hrefs(current_url, html):
                if href not in visited:
                    queue.append(href)

        context.close()
        browser.close()

    return persist_records(db_path=db_path, records=all_records)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", "--db-path", dest="db_path", default="data/tatemono_map.sqlite3")
    parser.add_argument("--start-url", required=True)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--sleep-ms", type=int, default=800)
    args = parser.parse_args()

    upserted, summary_count = ingest(
        start_url=args.start_url,
        db_path=args.db_path,
        max_pages=args.max_pages,
        sleep_ms=args.sleep_ms,
    )
    print(f"upserted raw_units/listings: {upserted}")
    print(f"rebuilt building_summaries: {summary_count}")


if __name__ == "__main__":
    main()
