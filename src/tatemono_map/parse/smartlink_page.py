from __future__ import annotations

import json
import logging
import re

from selectolax.parser import HTMLParser

from tatemono_map.db.repo import ListingRecord, connect, iter_raw_sources, upsert_listing
from tatemono_map.util.area import parse_area_sqm
from tatemono_map.util.money import parse_rent_yen
from tatemono_map.util.text import normalize_text

ROOM_RE = re.compile(r"(\d+[A-Za-z]?号室?)")
LOGGER = logging.getLogger(__name__)
KEYWORD_HINTS = ("賃料", "家賃", "共益費", "間取り", "専有面積", "所在地")


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
    for label in ["所在地", "号室", "家賃", "賃料", "共益費", "間取り", "専有面積"]:
        if label in pairs:
            continue
        m = re.search(rf"{re.escape(label)}\s*[:：]\s*([^\n]+)", text)
        if m:
            pairs[label] = normalize_text(m.group(1))
    return pairs


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


def _extract_from_embedded_json(html: str) -> list[dict[str, str | int | float | None]]:
    candidates: list[dict[str, str | int | float | None]] = []
    for payload in _iter_json_payloads(html):
        for node in _flatten_dict_nodes(payload):
            address = normalize_text(str(node.get("所在地") or node.get("address") or ""))
            rent_raw = node.get("賃料") or node.get("家賃") or node.get("rent")
            area_raw = node.get("専有面積") or node.get("面積") or node.get("area")
            if not address or (rent_raw is None and area_raw is None):
                continue
            candidates.append(
                {
                    "name": normalize_text(str(node.get("物件名") or node.get("name") or "名称不明")),
                    "address": address,
                    "room_label": normalize_text(str(node.get("号室") or node.get("room") or "")) or None,
                    "rent_yen": parse_rent_yen(str(rent_raw) if rent_raw is not None else None),
                    "maint_yen": parse_rent_yen(str(node.get("共益費") or node.get("maintenance") or "")),
                    "layout": normalize_text(str(node.get("間取り") or node.get("layout") or "")) or None,
                    "area_sqm": parse_area_sqm(str(area_raw) if area_raw is not None else None),
                }
            )
    return candidates


def parse_and_upsert(db_path: str) -> int:
    conn = connect(db_path)
    count = 0
    source_rows = list(iter_raw_sources(conn, "smartlink_page"))
    if not source_rows:
        conn.close()
        raise RuntimeError("No smartlink_page rows found in raw_sources")

    for row in source_rows:
        source_url = row["source_url"]
        fetched_at = row["fetched_at"]
        html = row["content"]
        has_keywords = any(keyword in html for keyword in KEYWORD_HINTS)
        LOGGER.debug(
            "smartlink parse input: url=%s html_len=%d has_keywords=%s",
            source_url,
            len(html),
            has_keywords,
        )

        row_count = 0
        tree = HTMLParser(html)
        cards = tree.css("article.property-card") or tree.css("article, .property-card, .result-item, li")
        for card in cards:
            pairs = _extract_pairs(card)
            address = normalize_text(pairs.get("所在地"))
            if not address:
                continue

            room_label = normalize_text(pairs.get("号室")) or None
            name, room_label = _guess_name_and_room(card, room_label)

            upsert_listing(
                conn,
                ListingRecord(
                    name=name,
                    address=address,
                    room_label=room_label,
                    rent_yen=parse_rent_yen(pairs.get("家賃") or pairs.get("賃料")),
                    maint_yen=parse_rent_yen(pairs.get("共益費")),
                    layout=normalize_text(pairs.get("間取り")) or None,
                    area_sqm=parse_area_sqm(pairs.get("専有面積")),
                    updated_at=fetched_at,
                    source_kind="smartlink_page",
                    source_url=source_url,
                ),
            )
            count += 1
            row_count += 1

        if row_count == 0:
            for item in _extract_from_embedded_json(html):
                upsert_listing(
                    conn,
                    ListingRecord(
                        name=str(item["name"]),
                        address=str(item["address"]),
                        room_label=item["room_label"],
                        rent_yen=item["rent_yen"],
                        maint_yen=item["maint_yen"],
                        layout=item["layout"],
                        area_sqm=item["area_sqm"],
                        updated_at=fetched_at,
                        source_kind="smartlink_page",
                        source_url=source_url,
                    ),
                )
                count += 1
                row_count += 1

    conn.close()
    if count <= 0:
        raise RuntimeError("smartlink_page parse produced 0 listings")
    return count
