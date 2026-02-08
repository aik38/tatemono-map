from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from tatemono_map.db.repo import ListingRecord, connect, upsert_listing
from tatemono_map.util.area import parse_area_sqm
from tatemono_map.util.money import parse_rent_yen
from tatemono_map.util.text import normalize_text

ROOM_RE = re.compile(r"(\d+[A-Za-z]?号室?)")


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


def parse_and_upsert(db_path: str) -> int:
    conn = connect(db_path)
    rows = conn.execute(
        "SELECT source_url, raw_html, fetched_at FROM raw_sources WHERE source_kind='smartlink_page' ORDER BY id ASC"
    ).fetchall()

    count = 0
    for row in rows:
        source_url = row["source_url"]
        fetched_at = row["fetched_at"]
        tree = HTMLParser(row["raw_html"])
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

    conn.close()
    return count
