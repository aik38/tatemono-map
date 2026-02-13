from __future__ import annotations

import argparse
import json
import re
from typing import Iterable
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from tatemono_map.db.keys import make_building_key, make_listing_key_for_smartlink
from tatemono_map.db.repo import ListingRecord, connect, iter_raw_sources
from tatemono_map.normalize.building_summaries import rebuild
from tatemono_map.util.area import parse_area_sqm
from tatemono_map.util.money import parse_rent_yen
from tatemono_map.util.text import normalize_text

ROOM_RE = re.compile(r"(\d+[A-Za-z]?号室?)")
KEYWORD_HINTS = ("賃料", "家賃", "共益費", "間取り", "専有面積", "所在地", "入居可能日")


def _extract_pairs(card) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for node in card.css("dt,th"):
        key = normalize_text(node.text())
        sib = node.next
        while sib is not None and sib.tag not in {"dd", "td"}:
            sib = sib.next
        if sib is not None:
            pairs[key] = normalize_text(sib.text(deep=True, separator=" "))

    text = normalize_text(card.text(deep=True, separator="\n"))
    for label in ["所在地", "号室", "家賃", "賃料", "共益費", "間取り", "専有面積", "入居可能日", "更新", "更新日時", "管理会社", "電話"]:
        if label in pairs:
            continue
        m = re.search(rf"{re.escape(label)}\s*[:：]\s*([^\n]+)", text)
        if m:
            pairs[label] = normalize_text(m.group(1))
    return pairs


def _extract_detail_url(card, page_url: str) -> str:
    anchor = card.css_first("a[href]")
    href = normalize_text(anchor.attributes.get("href")) if anchor is not None else ""
    if not href:
        return page_url
    return urljoin(page_url, href)


def _guess_name_and_room(card, room_label: str | None) -> tuple[str, str | None]:
    heading = card.css_first("h1,h2,h3,h4,.title,a")
    title = normalize_text(heading.text()) if heading is not None else ""
    if not room_label and title:
        m = ROOM_RE.search(title)
        if m:
            room_label = m.group(1)
    name = title
    if room_label:
        name = normalize_text(name.replace(room_label, ""))
    return (name or "名称不明", room_label)


def _iter_json_payloads(html: str):
    for m in re.finditer(r"\{[\s\S]{80,}\}", html):
        chunk = m.group(0)
        if "所在地" not in chunk and "賃料" not in chunk and "家賃" not in chunk:
            continue
        try:
            yield json.loads(chunk)
        except Exception:
            continue


def _flatten_dict_nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _flatten_dict_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _flatten_dict_nodes(child)


def _extract_from_embedded_json(html: str, page_url: str, fetched_at: str | None) -> list[ListingRecord]:
    records: list[ListingRecord] = []
    for payload in _iter_json_payloads(html):
        for node in _flatten_dict_nodes(payload):
            address = normalize_text(str(node.get("所在地") or node.get("address") or ""))
            rent_raw = node.get("賃料") or node.get("家賃") or node.get("rent")
            area_raw = node.get("専有面積") or node.get("面積") or node.get("area")
            if not address or (rent_raw is None and area_raw is None):
                continue
            room = normalize_text(str(node.get("号室") or node.get("room") or "")) or None
            source_url = normalize_text(str(node.get("url") or node.get("href") or ""))
            source_url = urljoin(page_url, source_url) if source_url else page_url
            records.append(
                ListingRecord(
                    name=normalize_text(str(node.get("物件名") or node.get("name") or "名称不明")),
                    address=address,
                    room_label=room,
                    rent_yen=parse_rent_yen(str(rent_raw) if rent_raw is not None else None),
                    maint_yen=parse_rent_yen(str(node.get("共益費") or node.get("maintenance") or "")),
                    layout=normalize_text(str(node.get("間取り") or node.get("layout") or "")) or None,
                    area_sqm=parse_area_sqm(str(area_raw) if area_raw is not None else None),
                    move_in_date=normalize_text(str(node.get("入居可能日") or node.get("move_in_date") or "")) or None,
                    updated_at=normalize_text(str(node.get("更新") or node.get("updated_at") or "")) or fetched_at,
                    source_kind="smartlink_page",
                    source_url=source_url,
                    management_company=normalize_text(str(node.get("管理会社") or node.get("management_company") or "")) or None,
                    management_phone=normalize_text(str(node.get("電話") or node.get("management_phone") or "")) or None,
                )
            )
    return records


def _parse_records(source_url: str, fetched_at: str | None, content: str | bytes) -> list[ListingRecord]:
    html = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else str(content)
    if not any(keyword in html for keyword in KEYWORD_HINTS):
        return []

    records: list[ListingRecord] = []
    tree = HTMLParser(html)
    cards = tree.css("article.property-card") or tree.css("article, .property-card, .result-item, li")
    for card in cards:
        pairs = _extract_pairs(card)
        address = normalize_text(pairs.get("所在地"))
        if not address:
            continue

        room_label = normalize_text(pairs.get("号室")) or None
        name, room_label = _guess_name_and_room(card, room_label)
        updated_at = normalize_text(pairs.get("更新日時") or pairs.get("更新")) or fetched_at
        records.append(
            ListingRecord(
                name=name,
                address=address,
                room_label=room_label,
                rent_yen=parse_rent_yen(pairs.get("家賃") or pairs.get("賃料")),
                maint_yen=parse_rent_yen(pairs.get("共益費")),
                layout=normalize_text(pairs.get("間取り")) or None,
                area_sqm=parse_area_sqm(pairs.get("専有面積")),
                updated_at=updated_at,
                source_kind="smartlink_page",
                source_url=_extract_detail_url(card, source_url),
                move_in_date=normalize_text(pairs.get("入居可能日")) or None,
                management_company=normalize_text(pairs.get("管理会社")) or None,
                management_phone=normalize_text(pairs.get("電話")) or None,
            )
        )

    if records:
        return records
    return _extract_from_embedded_json(html=html, page_url=source_url, fetched_at=fetched_at)


def _bulk_upsert(conn, records: Iterable[ListingRecord]) -> int:
    payload = []
    for record in records:
        building_key = make_building_key(record.name, record.address)
        listing_key = make_listing_key_for_smartlink(record.source_url, record.room_label)
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
    return len(payload)


def ingest(db_path: str) -> tuple[int, int]:
    conn = connect(db_path)
    source_rows = list(iter_raw_sources(conn, "smartlink_page"))
    if not source_rows:
        conn.close()
        raise RuntimeError("No smartlink_page rows found in raw_sources")

    all_records: list[ListingRecord] = []
    for row in source_rows:
        all_records.extend(_parse_records(row["source_url"], row["fetched_at"], row["content"]))

    if not all_records:
        conn.close()
        raise RuntimeError("smartlink_page parse produced 0 listings")

    upserted = _bulk_upsert(conn, all_records)
    conn.close()

    summary_count = rebuild(db_path)
    return upserted, summary_count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    args = parser.parse_args()

    upserted, summary_count = ingest(args.db)
    print(f"upserted raw_units/listings: {upserted}")
    print(f"rebuilt building_summaries: {summary_count}")


if __name__ == "__main__":
    main()
