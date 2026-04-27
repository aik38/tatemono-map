from __future__ import annotations
from pathlib import Path
import json
import os
import re
from bs4 import BeautifulSoup

REPO = Path(os.environ["TATEMONO_MAP_REPO"])
FIXTURE_DIR = REPO / "tests" / "fixtures" / "mansion_review_top15"
INPUT_HTML = Path(os.environ["MANSION_REVIEW_TOP15_SOURCE_HTML"])

PRICE_RE = re.compile(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?万円台?|\d+(?:\.\d+)?万円台?")
AREA_RE = re.compile(r"\d+(?:\.\d+)?m²")
LAYOUT_RE = re.compile(r"(?:ワンルーム|[1-9]\d?S?LDK|[1-9]\d?LDK|[1-9]\d?DK|[1-9]\d?K)")
FLOOR_RE = re.compile(r"\d+階")
DIRECTION_RE = re.compile(r"(?:南東|南西|北東|北西|東|西|南|北)")

def norm(text: str) -> str:
    return " ".join((text or "").replace("\u3000", " ").split())

def sales_table(card):
    for table in card.select("table.recommendTable"):
        th = table.select_one("th.size_title")
        if th and "このマンションの【中古】販売情報" in norm(th.get_text(" ", strip=True)):
            return table
    return None

def is_hidden_row(tr) -> bool:
    classes = " ".join(tr.get("class", []))
    style = (tr.get("style") or "").replace(" ", "").lower()
    attrs = " ".join(f"{k}={v}" for k, v in tr.attrs.items()).lower()

    hidden_tokens = [
        "display:none",
        "visibility:hidden",
        "aria-hidden=true",
        "hidden",
        "dnone",
        "hide",
        "hiddenrow",
        "close",
        "collapsed",
    ]
    blob = f"{classes} {style} {attrs}"
    return any(tok in blob for tok in hidden_tokens)

def first_match(pattern, text: str) -> str:
    m = pattern.search(text or "")
    return m.group(0) if m else ""

def parse_visible_rows(card):
    table = sales_table(card)
    rows = []
    if not table:
        return rows

    for tr in table.select("tbody.recommend_row > tr"):
        if is_hidden_row(tr):
            continue

        row_text = norm(tr.get_text(" ", strip=True))
        if not row_text:
            continue

        price_text = first_match(PRICE_RE, row_text)
        if not price_text:
            continue

        is_mosaic = (
            "無料会員登録でモザイクを消す" in row_text
            or "万円台" in price_text
            or "モザイク" in row_text
            or "---" in row_text
        )

        if is_mosaic:
            area_text = ""
            layout = ""
            floor = ""
            direction = ""
        else:
            area_text = first_match(AREA_RE, row_text)
            layout = first_match(LAYOUT_RE, row_text)
            floor = first_match(FLOOR_RE, row_text)
            direction = first_match(DIRECTION_RE, row_text)

        rows.append({
            "price_text": price_text,
            "area_text": area_text,
            "layout": layout,
            "floor": floor,
            "direction": direction,
            "is_mosaic": bool(is_mosaic),
        })

    return rows

def main():
    if not INPUT_HTML.exists():
        raise FileNotFoundError(f"INPUT_HTML not found: {INPUT_HTML}")

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    source_copy = FIXTURE_DIR / "fixture_source.html"
    source_copy.write_text(INPUT_HTML.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")

    soup = BeautifulSoup(source_copy.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    cards = soup.select("li.property-detail-list-item")[:15]
    if len(cards) < 15:
        raise RuntimeError(f"expected at least 15 property cards, got {len(cards)}")

    truth = {"source_file": str(INPUT_HTML), "top15": []}

    for idx, card in enumerate(cards, start=1):
        a = card.select_one(".property-detail-content__head-title a")
        if not a:
            raise RuntimeError(f"top15 card {idx} has no title link")

        building_name = norm(a.get_text(" ", strip=True))
        detail_url = (a.get("href") or "").strip()
        sales_rows = parse_visible_rows(card)

        card_text = norm(card.get_text(" ", strip=True))
        m = re.search(r"全\s*(\d+)\s*件を表示する", card_text)
        total_count_if_expandable = int(m.group(1)) if m else len(sales_rows)

        item_id = re.search(r"/mansion/(\d+)\.html", detail_url)
        id_part = item_id.group(1) if item_id else f"{idx:02d}"
        file_stem = f"{idx:02d}_{id_part}"

        card_path = FIXTURE_DIR / f"{file_stem}.html"
        card_path.write_text(str(card), encoding="utf-8")

        truth["top15"].append({
            "rank": idx,
            "file": card_path.name,
            "building_name": building_name,
            "detail_url": detail_url,
            "visible_row_count": len(sales_rows),
            "visible_exact_count": sum(1 for r in sales_rows if not r["is_mosaic"]),
            "visible_mosaic_count": sum(1 for r in sales_rows if r["is_mosaic"]),
            "total_count_if_expandable": total_count_if_expandable,
            "rows": sales_rows,
        })

    (FIXTURE_DIR / "top15_truth.json").write_text(
        json.dumps(truth, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"OK: wrote {len(cards)} card fixtures to {FIXTURE_DIR}")
    print(f"OK: wrote truth to {FIXTURE_DIR / 'top15_truth.json'}")

if __name__ == "__main__":
    main()
