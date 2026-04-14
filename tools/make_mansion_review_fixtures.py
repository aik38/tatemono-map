from pathlib import Path
import json
import os
from bs4 import BeautifulSoup

REPO = Path(os.environ.get("TATEMONO_MAP_REPO", Path(__file__).resolve().parents[1]))
INPUT_HTML = Path(os.environ["MANSION_REVIEW_FIXTURE_INPUT_HTML"])
OUT_DIR = REPO / "tests" / "fixtures" / "mansion_review"

TARGETS = [
    {
        "slug": "01_kokura_dc_tower",
        "names": ["小倉ＤＣタワー", "小倉DCタワー"],
        "truth": {
            "display_name": "小倉ＤＣタワー",
            "detail_url_suffix": "/mansion/598872.html",
            "total_count": 1,
            "exact_count": 0,
            "mosaic_count": 1,
            "exact_rows": []
        },
    },
    {
        "slug": "02_sunpark_kokura_tower_residence",
        "names": ["ザ・サンパーク小倉駅タワーレジデンス"],
        "truth": {
            "display_name": "ザ・サンパーク小倉駅タワーレジデンス",
            "detail_url_suffix": "/mansion/2175486.html",
            "total_count": 3,
            "exact_count": 0,
            "mosaic_count": 3,
            "exact_rows": []
        },
    },
    {
        "slug": "03_live_square_ocean_terrace",
        "names": ["ライブスクエア小倉駅オーシャンテラス"],
        "truth": {
            "display_name": "ライブスクエア小倉駅オーシャンテラス",
            "detail_url_suffix": "/mansion/1638926.html",
            "total_count": 1,
            "exact_count": 0,
            "mosaic_count": 1,
            "exact_rows": []
        },
    },
    {
        "slug": "04_sunrelius_kokura_ekiminami",
        "names": ["サンレリウス小倉駅南"],
        "truth": {
            "display_name": "サンレリウス小倉駅南",
            "detail_url_suffix": "/mansion/1638299.html",
            "total_count": 8,
            "exact_count": 4,
            "mosaic_count": 4,
            "exact_rows": [
                {"price_text": "4,498万円", "area_text": "66.41m²", "layout": "3LDK", "floor": "12階", "direction": "西"},
                {"price_text": "2,280万円", "area_text": "34.56m²", "layout": "1SLDK", "floor": "9階", "direction": "東"},
                {"price_text": "3,180万円", "area_text": "58.09m²", "layout": "2LDK", "floor": "6階", "direction": "東"},
                {"price_text": "4,498万円", "area_text": "69.19m²", "layout": "3LDK", "floor": "12階", "direction": "西"},
            ]
        },
    },
    {
        "slug": "05_livio_city_nakai_eastcourt",
        "names": ["リビオシティ小倉中井イーストコート"],
        "truth": {
            "display_name": "リビオシティ小倉中井イーストコート",
            "detail_url_suffix": "/mansion/758859.html",
            "total_count": 2,
            "exact_count": 2,
            "mosaic_count": 0,
            "exact_rows": [
                {"price_text": "3,280万円", "area_text": "82.83m²", "layout": "3SLDK", "floor": "3階", "direction": "南西"},
                {"price_text": "3,950万円", "area_text": "107.27m²", "layout": "3LDK", "floor": "10階", "direction": "南西"},
            ]
        },
    },
]

def normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\u3000", " ").split())

def card_name(card) -> str:
    a = card.select_one(".property-detail-content__head-title a")
    if a:
        return normalize_text(a.get_text(" ", strip=True))
    return normalize_text(card.get_text(" ", strip=True))

def find_card(soup: BeautifulSoup, names: list[str]):
    for li in soup.select("li.property-detail-list-item"):
        name = card_name(li)
        if any(n in name for n in names):
            return li
    return None

def trim_card(card) -> str:
    soup = BeautifulSoup(str(card), "html.parser")
    for bad in soup.select("script, style, noscript, iframe"):
        bad.decompose()
    return str(soup)

def main():
    if not INPUT_HTML.exists():
        raise FileNotFoundError(f"INPUT_HTML not found: {INPUT_HTML}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    html = INPUT_HTML.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    truth = {}

    for target in TARGETS:
        card = find_card(soup, target["names"])
        if card is None:
            raise RuntimeError(f"Target card not found: {target['slug']} / {target['names']}")
        (OUT_DIR / f"{target['slug']}.html").write_text(trim_card(card), encoding="utf-8")
        truth[target["slug"]] = target["truth"]

    (OUT_DIR / "truth.json").write_text(
        json.dumps(truth, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"OK: fixtures written to {OUT_DIR}")
    print(f"OK: truth written to {OUT_DIR / 'truth.json'}")

if __name__ == "__main__":
    main()
