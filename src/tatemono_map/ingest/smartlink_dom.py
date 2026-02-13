from __future__ import annotations

import argparse
import json
import os
import re
import traceback
from collections import Counter
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from tatemono_map.db.keys import make_building_key, make_listing_key_for_smartlink
from tatemono_map.db.repo import ListingRecord, connect
from tatemono_map.ingest.ulucks_playwright import _extract_pagination_hrefs
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.util.area import parse_area_sqm
from tatemono_map.util.money import parse_rent_yen
from tatemono_map.util.text import normalize_text

_CARD_FIELD_LABELS = ("物件名", "号室", "所在地", "家賃", "更新日時")
_CARD_SELECTORS = (
    "table.listing_card",
    ".listing_card",
    ".property-card",
    ".property_card",
    ".result-item",
    ".result_item",
)
_ROOM_SUFFIX_RE = re.compile(r"^(?P<name>.+?)[\s　]+(?P<room>[A-Za-z]?\d{2,4}(?:号室)?)$")


@dataclass(frozen=True)
class _DebugPageSnapshot:
    url: str
    title: str
    html: str




def _room_label_for_key(record: ListingRecord) -> str | None:
    if record.room_label:
        return record.room_label
    return "|".join(
        [
            normalize_text(record.name),
            normalize_text(record.layout or ""),
            str(record.area_sqm or ""),
            str(record.rent_yen or ""),
        ]
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
    resolved = urljoin(current_url, value)
    return resolved or None


def _iter_ancestors(node, max_depth: int = 6):
    depth = 0
    current = node.parent
    while current is not None and current.tag != "-undef" and depth < max_depth:
        yield current
        current = current.parent
        depth += 1


def _extract_kv_fields(card) -> dict[str, str]:
    fields: dict[str, str] = {}
    for row in card.css("tr"):
        cells = row.css("th, td")
        if len(cells) < 2:
            continue
        key = normalize_text(cells[0].text(deep=True, separator=" "))
        value = normalize_text(cells[1].text(deep=True, separator=" "))
        if key and value:
            fields[key] = value

    terms = card.css("dt")
    definitions = card.css("dd")
    for idx, term in enumerate(terms):
        if idx >= len(definitions):
            break
        key = normalize_text(term.text(deep=True, separator=" "))
        value = normalize_text(definitions[idx].text(deep=True, separator=" "))
        if key and value:
            fields[key] = value

    return fields


def _field_from_labels(fields: dict[str, str], *labels: str) -> str:
    for label in labels:
        if label in fields and fields[label]:
            return fields[label]
    return ""


def _split_building_and_room(name_text: str, explicit_room: str | None = None) -> tuple[str, str | None]:
    name = normalize_text(name_text)
    room = normalize_text(explicit_room or "") or None
    if room:
        name = name.replace(room, "").strip(" /　")
        return name, room

    matched = _ROOM_SUFFIX_RE.match(name)
    if matched:
        return matched.group("name").strip(), matched.group("room").strip()
    return name, None




def _extract_table_rows_as_cards(soup: HTMLParser) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    for table in soup.css("table"):
        rows = table.css("tr")
        if len(rows) < 2:
            continue
        header_cells = rows[0].css("th, td")
        headers = [normalize_text(cell.text(deep=True, separator=" ")) for cell in header_cells]
        joined = " ".join(headers)
        if "物件" not in joined or "所在地" not in joined or "家賃" not in joined:
            continue

        header_idx: dict[str, int] = {}
        for idx, header in enumerate(headers):
            if ("物件" in header or "建物" in header) and "name" not in header_idx:
                header_idx["name"] = idx
            if ("号室" in header or "部屋" in header) and "room" not in header_idx:
                header_idx["room"] = idx
            if "所在" in header and "address" not in header_idx:
                header_idx["address"] = idx
            if ("家賃" in header or "賃料" in header) and "rent" not in header_idx:
                header_idx["rent"] = idx
            if ("間取" in header or "間取り" in header) and "layout" not in header_idx:
                header_idx["layout"] = idx
            if ("面積" in header or "㎡" in header) and "area" not in header_idx:
                header_idx["area"] = idx
            if "更新" in header and "updated" not in header_idx:
                header_idx["updated"] = idx
            if "入居" in header and "move_in" not in header_idx:
                header_idx["move_in"] = idx
            if ("管理費" in header or "共益費" in header) and "maint" not in header_idx:
                header_idx["maint"] = idx

        if "name" not in header_idx or "address" not in header_idx:
            continue

        for row in rows[1:]:
            cells = row.css("td")
            if not cells:
                continue
            values = [normalize_text(cell.text(deep=True, separator=" ")) for cell in cells]
            if not any(values):
                continue
            fields: dict[str, str] = {}
            fields["物件名"] = values[header_idx["name"]] if header_idx["name"] < len(values) else ""
            fields["所在地"] = values[header_idx["address"]] if header_idx["address"] < len(values) else ""
            if "room" in header_idx and header_idx["room"] < len(values):
                fields["号室"] = values[header_idx["room"]]
            if "rent" in header_idx and header_idx["rent"] < len(values):
                fields["家賃"] = values[header_idx["rent"]]
            if "layout" in header_idx and header_idx["layout"] < len(values):
                fields["間取り"] = values[header_idx["layout"]]
            if "area" in header_idx and header_idx["area"] < len(values):
                fields["専有面積"] = values[header_idx["area"]]
            if "updated" in header_idx and header_idx["updated"] < len(values):
                fields["更新日時"] = values[header_idx["updated"]]
            if "move_in" in header_idx and header_idx["move_in"] < len(values):
                fields["入居可能日"] = values[header_idx["move_in"]]
            if "maint" in header_idx and header_idx["maint"] < len(values):
                fields["管理費"] = values[header_idx["maint"]]

            detail_anchor = row.css_first("a[href]")
            if detail_anchor is not None:
                fields["__detail_href"] = detail_anchor.attributes.get("href") or ""

            cards.append(fields)

    return cards

def _extract_cards(soup: HTMLParser) -> list[Any]:
    cards: list[Any] = []
    seen: set[int] = set()

    def _append(node) -> None:
        node_id = node.mem_id
        if node_id in seen:
            return
        seen.add(node_id)
        cards.append(node)

    for selector in _CARD_SELECTORS:
        for node in soup.css(selector):
            _append(node)

    for anchor in soup.css("a[href]"):
        anchor_text = normalize_text(anchor.text(deep=True, separator=" "))
        href = normalize_text(anchor.attributes.get("href") or "")
        if "詳細" not in anchor_text and "/view/smartlink" not in href:
            continue
        for ancestor in _iter_ancestors(anchor):
            block_text = normalize_text(ancestor.text(deep=True, separator=" "))
            score = sum(1 for label in _CARD_FIELD_LABELS if label in block_text)
            if score >= 3:
                _append(ancestor)
                break

    return cards


def _parse_card(card, base_url: str) -> ListingRecord | None:
    fields = _extract_kv_fields(card)
    name_raw = _field_from_labels(fields, "物件名/号室", "物件名", "建物名")
    room_raw = _field_from_labels(fields, "号室", "部屋")
    address = _field_from_labels(fields, "所在地", "住所")
    rent_raw = _field_from_labels(fields, "家賃", "賃料")
    maint_raw = _field_from_labels(fields, "管理費", "共益費", "諸費用")
    layout = _field_from_labels(fields, "間取り", "間取") or None
    area_raw = _field_from_labels(fields, "専有面積", "面積")
    move_in = _field_from_labels(fields, "入居可能日", "入居") or None
    updated = _field_from_labels(fields, "更新日時", "更新日", "掲載日") or None

    if not name_raw:
        headline = card.css_first("h1, h2, h3, h4, .title, .name")
        if headline is not None:
            name_raw = normalize_text(headline.text(deep=True, separator=" "))

    if not address or not rent_raw:
        card_text = normalize_text(card.text(deep=True, separator=" "))
        for label in ("所在地", "住所"):
            if not address and label in card_text:
                address = card_text.split(label, 1)[1].split("家賃", 1)[0].strip(" ：:")
        if not rent_raw and "家賃" in card_text:
            rent_raw = card_text.split("家賃", 1)[1].split("間取り", 1)[0].strip(" ：:")

    name, room_label = _split_building_and_room(name_raw, explicit_room=room_raw)
    if not name or not address:
        return None

    detail_url = _to_absolute_href(base_url, fields.get("__detail_href"))
    for anchor in card.css("a[href]"):
        anchor_text = normalize_text(anchor.text(deep=True, separator=" "))
        href = anchor.attributes.get("href")
        if "詳細" in anchor_text:
            detail_url = _to_absolute_href(base_url, href)
            break
        if detail_url is None:
            detail_url = _to_absolute_href(base_url, href)

    return ListingRecord(
        name=name,
        address=address,
        room_label=room_label,
        rent_yen=parse_rent_yen(rent_raw),
        maint_yen=parse_rent_yen(maint_raw),
        layout=layout,
        area_sqm=parse_area_sqm(area_raw),
        move_in_date=move_in,
        updated_at=updated,
        source_kind="smartlink_dom",
        source_url=detail_url or base_url,
    )


def _record_from_fields(fields: dict[str, str], base_url: str) -> ListingRecord | None:
    name_raw = _field_from_labels(fields, "物件名/号室", "物件名", "建物名")
    room_raw = _field_from_labels(fields, "号室", "部屋")
    address = _field_from_labels(fields, "所在地", "住所")
    name, room_label = _split_building_and_room(name_raw, explicit_room=room_raw)
    if not name or not address:
        return None

    detail_url = _to_absolute_href(base_url, fields.get("__detail_href"))
    return ListingRecord(
        name=name,
        address=address,
        room_label=room_label,
        rent_yen=parse_rent_yen(_field_from_labels(fields, "家賃", "賃料")),
        maint_yen=parse_rent_yen(_field_from_labels(fields, "管理費", "共益費", "諸費用")),
        layout=_field_from_labels(fields, "間取り", "間取") or None,
        area_sqm=parse_area_sqm(_field_from_labels(fields, "専有面積", "面積")),
        move_in_date=_field_from_labels(fields, "入居可能日", "入居") or None,
        updated_at=_field_from_labels(fields, "更新日時", "更新日", "掲載日") or None,
        source_kind="smartlink_dom",
        source_url=detail_url or base_url,
    )


def extract_records(source_url: str, html: str) -> list[ListingRecord]:
    soup = HTMLParser(html)
    primary_cards = _extract_cards(soup)
    fallback_cards = _extract_table_rows_as_cards(soup)

    seen: set[str] = set()
    records: list[ListingRecord] = []

    def _consume(cards: list[Any]) -> None:
        for card in cards:
            record = _parse_card(card, source_url)
            if not record:
                continue
            rec_key = make_listing_key_for_smartlink(record.source_url, _room_label_for_key(record))
            if rec_key in seen:
                continue
            seen.add(rec_key)
            records.append(record)

    _consume(primary_cards)
    if not records:
        for field_map in fallback_cards:
            record = _record_from_fields(field_map, source_url)
            if not record:
                continue
            rec_key = make_listing_key_for_smartlink(record.source_url, _room_label_for_key(record))
            if rec_key in seen:
                continue
            seen.add(rec_key)
            records.append(record)
    return records


def _collect_parse_debug_meta(source_url: str, html: str) -> dict[str, int | str]:
    tree = HTMLParser(html)
    cards = _extract_cards(tree)
    table_row_cards = _extract_table_rows_as_cards(tree)
    if not cards:
        cards = table_row_cards
    detail_links = 0
    cards_with_name_label = 0
    for card in cards:
        if isinstance(card, dict):
            text = normalize_text(" ".join(card.values()))
            if "物件名" in text:
                cards_with_name_label += 1
            if card.get("__detail_href"):
                detail_links += 1
            continue

        text = normalize_text(card.text(deep=True, separator=" "))
        if "物件名" in text:
            cards_with_name_label += 1
        if any("詳細" in normalize_text(a.text(deep=True, separator=" ")) for a in card.css("a[href]")):
            detail_links += 1

    label_counter = Counter()
    body_text = normalize_text(tree.body.text(deep=True, separator=" ")) if tree.body else ""
    for label in ("更新日時", "物件名", "所在地", "家賃"):
        label_counter[label] = body_text.count(label)

    return {
        "source_url": source_url,
        "found_cards": len(cards),
        "found_table_row_cards": len(table_row_cards),
        "cards_with_name_label": cards_with_name_label,
        "cards_with_detail_link": detail_links,
        "found_update_labels": label_counter["更新日時"],
        "found_name_labels": label_counter["物件名"],
        "found_address_labels": label_counter["所在地"],
        "found_rent_labels": label_counter["家賃"],
        "found_pagination_links": len(tree.css("a[href*='/view/smartlink/page:']")),
    }


def _bulk_upsert(db_path: str, records: list[ListingRecord]) -> int:
    conn = connect(db_path)
    payload = []
    for record in records:
        building_key = make_building_key(record.name, record.address)
        listing_key = make_listing_key_for_smartlink(record.source_url, _room_label_for_key(record))
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
                    parse_meta = _collect_parse_debug_meta(current_url, html)
                    parse_meta["record_count"] = len(page_records)
                    _dump_debug(
                        debug_root,
                        page,
                        len(visited),
                        "parse_failed",
                        reason="0 records on page",
                        extra_meta=parse_meta,
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
