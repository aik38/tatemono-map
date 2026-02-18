from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlparse

from selectolax.parser import HTMLParser

DEFAULT_IN = Path("tmp/manual/inputs/html_saved")
DEFAULT_OUT = Path("tmp/manual/outputs/mansion_review")

CITY_MAP = {
    "1616": "門司区",
    "1619": "小倉北区",
}


@dataclass
class Row:
    building_name: str
    address: str
    area: str
    city: str
    ward: str
    source_url: str
    source_file: str


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _guess_source_url(tree: HTMLParser, html: str) -> str:
    for css in ('meta[property="og:url"]', 'link[rel="canonical"]'):
        node = tree.css_first(css)
        if node and node.attributes.get("content"):
            return _clean(node.attributes["content"])
        if node and node.attributes.get("href"):
            return _clean(node.attributes["href"])

    m = re.search(r"https?://[^\s\"'<>]+", html)
    return _clean(m.group(0)) if m else ""


def _extract_area_city_ward(source_url: str) -> tuple[str, str, str]:
    if not source_url:
        return "", "", ""
    parsed = urlparse(source_url)
    query = parse_qs(parsed.query)

    area = "北九州市"
    city = ""
    ward = ""

    sub_cities = query.get("sub_city[]", [])
    for city_id in sub_cities:
        if city_id in CITY_MAP:
            ward = CITY_MAP[city_id]
            city = "北九州市"
            break

    city_match = re.search(r"/city/(\d+)\.html", parsed.path)
    if city_match and city_match.group(1) == "400001":
        city = "北九州市"

    return area, city, ward


def _extract_address(tree: HTMLParser) -> str:
    full_text = _clean(tree.text(separator=" "))
    m = re.search(r"(福岡県)?北九州市[^\s]{0,10}区[^\s]{0,80}", full_text)
    return _clean(m.group(0)) if m else ""


def _extract_building_candidates(tree: HTMLParser, html: str) -> list[str]:
    names: list[str] = []

    title = tree.css_first("title")
    if title and title.text():
        base = re.split(r"[|｜]\s*", title.text(), maxsplit=1)[0]
        base = re.sub(r"\d+号室", "", base)
        names.append(_clean(base))

    for node in tree.css("h1, h2"):
        txt = _clean(node.text())
        if txt:
            txt = re.sub(r"\d+号室", "", txt)
            names.append(txt)

    for a in tree.css("a[href]"):
        href = a.attributes.get("href", "")
        txt = _clean(a.text())
        if re.search(r"/(mansion|chintai)/\d+", href) and txt and txt not in {"詳細", "詳しく見る"}:
            names.append(txt)

    for m in re.finditer(r'"name"\s*:\s*"([^\"]{2,120})"', html):
        names.append(_clean(m.group(1)))

    deduped: list[str] = []
    seen: set[str] = set()
    for name in names:
        if len(name) < 2:
            continue
        if any(token in name for token in ["マンションレビュー", "賃貸", "検索", "ページ"]):
            continue
        if name in seen:
            continue
        seen.add(name)
        deduped.append(name)
    return deduped


def parse_html_file(path: Path) -> list[Row]:
    html = path.read_text(encoding="utf-8", errors="ignore")
    tree = HTMLParser(html)

    source_url = _guess_source_url(tree, html)
    area, city, ward = _extract_area_city_ward(source_url)
    address = _extract_address(tree)

    rows = [
        Row(
            building_name=name,
            address=address,
            area=area,
            city=city,
            ward=ward,
            source_url=source_url,
            source_file=path.name,
        )
        for name in _extract_building_candidates(tree, html)
    ]
    return rows


def collect_input_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    return sorted(p for p in input_path.rglob("*.html") if p.is_file())


def write_rows(rows: Iterable[Row], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["building_name", "address", "area", "city", "ward", "source_url", "source_file"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def main() -> int:
    ap = argparse.ArgumentParser(description="Convert saved mansion-review HTML files to CSV")
    ap.add_argument("--input", default=str(DEFAULT_IN), help="Input file or directory containing *.html")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT), help="Output root directory")
    ap.add_argument("--timestamp", default="", help="Optional timestamp (yyyyMMdd_HHmmss)")
    args = ap.parse_args()

    input_path = Path(args.input)
    files = collect_input_files(input_path)
    if not files:
        raise SystemExit(f"No html files found: {input_path}")

    ts = args.timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir) / ts
    out_csv = out_dir / f"mansion_review_{ts}.csv"

    all_rows: list[Row] = []
    for file in files:
        all_rows.extend(parse_html_file(file))

    write_rows(all_rows, out_csv)
    print(f"[OK] files={len(files)} rows={len(all_rows)} -> {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
