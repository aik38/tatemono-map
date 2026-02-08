from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from selectolax.parser import HTMLParser

from tatemono_map.util.area import parse_area_sqm
from tatemono_map.util.money import parse_rent_yen
from tatemono_map.util.text import normalize_text


@dataclass
class ParsedListing:
    name: str
    address: str
    rent_yen: int | None
    area_sqm: float | None
    layout: str | None
    updated_at: str


def _find_labeled(tree: HTMLParser, labels: list[str]) -> str | None:
    for node in tree.css("th,dt"):
        key = normalize_text(node.text())
        if any(label in key for label in labels):
            sib = node.next
            while sib is not None and sib.tag not in {"td", "dd"}:
                sib = sib.next
            if sib is not None:
                return normalize_text(sib.text(deep=True, separator=" "))
    body = normalize_text(tree.body.text(deep=True, separator="\n") if tree.body else tree.text())
    for label in labels:
        m = re.search(rf"{re.escape(label)}\s*[:：]?\s*([^\n]+)", body)
        if m:
            return normalize_text(m.group(1))
    return None


def parse_smartview_html(html: str, fetched_at: str | None = None) -> ParsedListing:
    tree = HTMLParser(html)
    name = _find_labeled(tree, ["建物名", "物件名", "マンション名"]) or normalize_text((tree.css_first("h1") or tree.css_first("title")).text() if (tree.css_first("h1") or tree.css_first("title")) else "")
    address = _find_labeled(tree, ["所在地", "住所"]) or ""
    rent_text = _find_labeled(tree, ["賃料", "家賃"]) or tree.text()
    area_text = _find_labeled(tree, ["専有面積", "面積"]) or tree.text()
    layout = _find_labeled(tree, ["間取り"])
    if layout:
        m = re.search(r"\d(?:R|K|DK|LDK)", layout, re.IGNORECASE)
        layout = m.group(0).upper() if m else layout
    updated = _find_labeled(tree, ["更新", "最終更新"])
    if not updated:
        updated = fetched_at or datetime.now(timezone.utc).isoformat()

    return ParsedListing(
        name=name or "名称不明",
        address=address,
        rent_yen=parse_rent_yen(rent_text),
        area_sqm=parse_area_sqm(area_text),
        layout=layout,
        updated_at=updated,
    )
