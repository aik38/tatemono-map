from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
import urllib.parse
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests
from selectolax.parser import HTMLParser, Node


def _resolve_db_path(db_arg: str | None) -> Path:
    if db_arg:
        return Path(db_arg).expanduser().resolve()
    return Path("data/tatemono_map.sqlite3").resolve()


def _ensure_parent_dir(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)


def _ensure_tables(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS building_summaries (
            building_key TEXT PRIMARY KEY,
            name TEXT,
            raw_name TEXT,
            address TEXT,
            vacancy_status TEXT,
            listings_count INTEGER,
            layout_types_json TEXT,
            rent_min INTEGER,
            rent_max INTEGER,
            area_min REAL,
            area_max REAL,
            last_updated TEXT,
            updated_at TEXT,
            rent_yen_min INTEGER,
            rent_yen_max INTEGER,
            area_sqm_min REAL,
            area_sqm_max REAL
        )
        """
    )


FORBIDDEN_OUTPUT_PATTERNS = [
    re.compile(r"(?:mail=|mailto:)", re.IGNORECASE),
    re.compile(r"(?:tel|fax)\s*[:：]?", re.IGNORECASE),
    re.compile(r"担当者"),
    re.compile(r"元付"),
    re.compile(r"会社情報"),
]


@dataclass
class SmartlinkCard:
    smartview_id: str
    building_title_raw: str
    building_name: str
    address: str | None
    rent_yen: int | None
    area_m2: float | None
    layout: str | None
    updated_at: str | None
    source_page: int


@dataclass
class BuildingSummary:
    building_name: str
    address: str | None
    vacancy_count: int
    rent_yen_min: int | None
    rent_yen_max: int | None
    area_m2_min: float | None
    area_m2_max: float | None
    layouts: list[str]


def _redact_url_for_log(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    redacted = [(k, "REDACTED" if k.lower() == "mail" else v) for k, v in q]
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(redacted)))


def _assert_safe_output(value: str | None) -> None:
    if not value:
        return
    for pat in FORBIDDEN_OUTPUT_PATTERNS:
        if pat.search(value):
            raise ValueError("forbidden sensitive token detected in output")


def _normalize_building_name(title: str) -> str:
    t = unicodedata.normalize("NFKC", title)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s*(?:\d+[A-Za-z]?号(?:室)?|\d+[A-Za-z]?室|\d+階|[A-Za-z]?\d{2,4})\s*$", "", t)
    return t.strip() or title.strip()


def _parse_money(text: str) -> int | None:
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*万", text)
    if m:
        return int(float(m.group(1)) * 10000)
    m2 = re.search(r"\b([0-9]{3,})\b", text.replace(",", ""))
    return int(m2.group(1)) if m2 else None


def _parse_area(text: str) -> float | None:
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:㎡|m2|m\^2)", text, flags=re.IGNORECASE)
    return float(m.group(1)) if m else None


def _parse_layout(text: str) -> str | None:
    m = re.search(r"\b\d(?:R|K|DK|LDK)\b", text, flags=re.IGNORECASE)
    return m.group(0).upper() if m else None


def _extract_smartview_id(href: str) -> str | None:
    m = re.search(r"/view/smartview/([^/?#]+)/?", href)
    return m.group(1) if m else None


def _node_text(node: Node | None) -> str:
    return (node.text(deep=True, separator=" ").strip() if node else "")


def _find_card_container(anchor: Node) -> Node:
    candidates: list[Node] = []
    cur = anchor
    while cur is not None:
        if cur.tag in {"li", "article", "section", "tr", "div"}:
            text = _node_text(cur)
            if any(h in text for h in ["所在地", "賃料", "㎡", "間取り"]):
                candidates.append(cur)
        cur = cur.parent
    return candidates[0] if candidates else (anchor.parent or anchor)


def _extract_labeled_text(card: Node, label: str) -> str | None:
    for th in card.css("th,dt"):
        if label in _node_text(th):
            sib = th.next
            while sib is not None and sib.tag not in {"td", "dd"}:
                sib = sib.next
            if sib is not None:
                return _node_text(sib)
    text = card.text(deep=True, separator="\n")
    m = re.search(rf"{re.escape(label)}\s*[:：]?\s*([^\n]+)", text)
    return m.group(1).strip() if m else None


def parse_smartlink_cards(html_text: str, *, source_page: int) -> list[SmartlinkCard]:
    tree = HTMLParser(html_text)
    cards: dict[str, SmartlinkCard] = {}
    for a in tree.css('a[href*="/view/smartview/"]'):
        href = a.attributes.get("href", "")
        sid = _extract_smartview_id(href)
        if not sid or sid in cards:
            continue
        container = _find_card_container(a)
        title_raw = _node_text(a) or "(名称未設定)"
        whole_text = container.text(deep=True, separator="\n")
        address = _extract_labeled_text(container, "所在地")
        rent_t = _extract_labeled_text(container, "賃料") or whole_text
        area_t = _extract_labeled_text(container, "専有面積") or whole_text
        layout_t = _extract_labeled_text(container, "間取り") or whole_text
        updated = _extract_labeled_text(container, "更新")
        card = SmartlinkCard(
            smartview_id=sid,
            building_title_raw=title_raw,
            building_name=_normalize_building_name(title_raw),
            address=address,
            rent_yen=_parse_money(rent_t),
            area_m2=_parse_area(area_t),
            layout=_parse_layout(layout_t),
            updated_at=updated,
            source_page=source_page,
        )
        _assert_safe_output(card.building_title_raw)
        _assert_safe_output(card.address)
        cards[sid] = card
    return list(cards.values())


def aggregate_building_summaries(cards: list[SmartlinkCard]) -> list[BuildingSummary]:
    grouped: dict[tuple[str, str], list[SmartlinkCard]] = {}
    for c in cards:
        name = re.sub(r"\s+", "", c.building_name or "")
        addr = re.sub(r"[\s、,。.-]", "", c.address or "")
        grouped.setdefault((name, addr), []).append(c)

    out: list[BuildingSummary] = []
    for rows in grouped.values():
        rents = [r.rent_yen for r in rows if r.rent_yen is not None]
        areas = [r.area_m2 for r in rows if r.area_m2 is not None]
        layouts = sorted({r.layout for r in rows if r.layout})
        out.append(
            BuildingSummary(
                building_name=rows[0].building_name,
                address=rows[0].address,
                vacancy_count=len(rows),
                rent_yen_min=min(rents) if rents else None,
                rent_yen_max=max(rents) if rents else None,
                area_m2_min=min(areas) if areas else None,
                area_m2_max=max(areas) if areas else None,
                layouts=layouts,
            )
        )
    return out


def _fetch_with_retry(url: str, *, timeout_s: float, retry: int, sleep_s: float) -> str:
    for i in range(retry + 1):
        try:
            r = requests.get(url, timeout=timeout_s, headers={"User-Agent": "tatemono-map/phase-a"})
            r.raise_for_status()
            return r.text
        except requests.RequestException:
            if i >= retry:
                raise
            time.sleep(sleep_s)
    raise RuntimeError("unreachable")


def _build_page_url(base_url: str, page: int) -> str:
    parsed = urllib.parse.urlparse(base_url)
    path = re.sub(r"/page:\d+/?", "/", parsed.path).rstrip("/")
    page_path = f"{path}/" if page == 1 else f"{path}/page:{page}/"
    return urllib.parse.urlunparse(parsed._replace(path=page_path))


def run_phase_a(*, url: str | None, html_files: list[Path] | None, max_pages: int, sleep_s: float, timeout_s: float, retry: int, cache_dir: Path | None) -> tuple[list[SmartlinkCard], list[BuildingSummary]]:
    cards: list[SmartlinkCard] = []
    for page in range(1, max_pages + 1):
        if html_files:
            if page > len(html_files):
                break
            html_text = html_files[page - 1].read_text(encoding="utf-8")
        else:
            assert url
            page_url = _build_page_url(url, page)
            html_text = _fetch_with_retry(page_url, timeout_s=timeout_s, retry=retry, sleep_s=sleep_s)
            if cache_dir:
                cache_dir.mkdir(parents=True, exist_ok=True)
                (cache_dir / f"smartlink_page_{page}.html").write_text(html_text, encoding="utf-8")
        page_cards = parse_smartlink_cards(html_text, source_page=page)
        if not page_cards:
            break
        seen = {c.smartview_id for c in cards}
        cards.extend([c for c in page_cards if c.smartview_id not in seen])
        time.sleep(sleep_s)
    return cards, aggregate_building_summaries(cards)


def _write_outputs(cards: list[SmartlinkCard], summaries: list[BuildingSummary], *, out_json: Path | None, out_csv: Path | None) -> None:
    if out_json:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps({"cards": [asdict(c) for c in cards], "building_summaries": [asdict(s) for s in summaries]}, ensure_ascii=False, indent=2), encoding="utf-8")
    if out_csv:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        headers = ["building_name", "address", "vacancy_count", "rent_yen_min", "rent_yen_max", "area_m2_min", "area_m2_max", "layouts"]
        with out_csv.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for row in summaries:
                d = asdict(row)
                d["layouts"] = json.dumps(d["layouts"], ensure_ascii=False)
                writer.writerow(d)


def _upsert_building_summaries(db_path: Path, summaries: list[BuildingSummary]) -> None:
    import sqlite3

    _ensure_parent_dir(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        _ensure_tables(conn)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for row in summaries:
            key_src = f"{row.building_name}|{row.address or ''}"
            building_key = hashlib.sha256(key_src.encode("utf-8")).hexdigest()
            conn.execute(
                """
                INSERT INTO building_summaries (
                    building_key, name, raw_name, address, vacancy_status, listings_count, layout_types_json,
                    rent_min, rent_max, area_min, area_max, last_updated, updated_at,
                    rent_yen_min, rent_yen_max, area_sqm_min, area_sqm_max
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(building_key) DO UPDATE SET
                    listings_count=excluded.listings_count,
                    layout_types_json=excluded.layout_types_json,
                    rent_min=COALESCE(excluded.rent_min, building_summaries.rent_min),
                    rent_max=COALESCE(excluded.rent_max, building_summaries.rent_max),
                    area_min=COALESCE(excluded.area_min, building_summaries.area_min),
                    area_max=COALESCE(excluded.area_max, building_summaries.area_max),
                    updated_at=excluded.updated_at
                """,
                (building_key, row.building_name, row.building_name, row.address, "vacant" if row.vacancy_count > 0 else "unknown", row.vacancy_count, json.dumps(row.layouts, ensure_ascii=False), row.rent_yen_min, row.rent_yen_max, row.area_m2_min, row.area_m2_max, now, now, row.rent_yen_min, row.rent_yen_max, row.area_m2_min, row.area_m2_max),
            )
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ulucks Phase A: parse smartlink listing pages only and build summaries")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="smartlink URL")
    src.add_argument("--html", nargs="+", help="saved smartlink HTML files (redacted)")
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--retry", type=int, default=2)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument("--out-csv", type=Path, default=None)
    parser.add_argument("--db", default=None, help="upsert summaries into SQLite")
    args = parser.parse_args()

    html_files = [Path(p) for p in args.html] if args.html else None
    cards, summaries = run_phase_a(url=args.url, html_files=html_files, max_pages=args.max_pages, sleep_s=args.sleep, timeout_s=args.timeout, retry=args.retry, cache_dir=args.cache_dir)
    _write_outputs(cards, summaries, out_json=args.out_json, out_csv=args.out_csv)
    if args.db:
        _upsert_building_summaries(_resolve_db_path(args.db), summaries)

    source = _redact_url_for_log(args.url) if args.url else f"html:{len(html_files or [])}"
    print(f"Phase A completed: cards={len(cards)} summaries={len(summaries)} source={source}")


if __name__ == "__main__":
    main()
