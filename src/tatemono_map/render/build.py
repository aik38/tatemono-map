from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from tatemono_map.api.database import get_engine, init_db

ALLOWED_VACANCY_STATUS = {"空室あり", "満室"}
BUILDING_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
FORBIDDEN_PATTERNS = [
    re.compile(r"号室"),
    re.compile(r"参照元"),
    re.compile(r"元付"),
    re.compile(r"管理会社"),
    re.compile(r"見積"),
    re.compile(r"\.pdf\b", re.IGNORECASE),
    re.compile(r"https?://", re.IGNORECASE),
    re.compile(r"\bURL\b", re.IGNORECASE),
]


def _parse_layout_types(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if isinstance(loaded, list):
        return [str(item) for item in loaded]
    return []


def _format_range(min_value: Any, max_value: Any, unit: str) -> str:
    if min_value is None and max_value is None:
        return "—"
    if min_value is None:
        return f"{max_value}{unit}"
    if max_value is None:
        return f"{min_value}{unit}"
    return f"{min_value}{unit}〜{max_value}{unit}"


def _normalize_vacancy_status(value: str | None) -> str:
    if value in ALLOWED_VACANCY_STATUS:
        return value
    raise ValueError(f"Vacancy status must be one of {sorted(ALLOWED_VACANCY_STATUS)}: {value}")


def _ensure_building_key(key: str) -> None:
    if not BUILDING_KEY_PATTERN.match(key):
        raise ValueError(f"Invalid building_key for static output: {key}")


def _assert_safe_html(content: str, label: str) -> None:
    for pattern in FORBIDDEN_PATTERNS:
        if pattern.search(content):
            raise ValueError(f"Forbidden content detected in {label}: {pattern.pattern}")


def _render_index(buildings: list[dict[str, Any]]) -> str:
    items = []
    for building in buildings:
        key = building["building_key"]
        name = html.escape(building["name"] or "")
        items.append(f'<li><a href="b/{key}.html">{name}</a></li>')
    items_html = "\n".join(items) if items else "<li>公開建物はまだありません。</li>"
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>建物一覧 | 建物マップ</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;max-width:920px;margin:24px auto;padding:0 16px;line-height:1.6}}
  </style>
</head>
<body>
  <h1>建物一覧</h1>
  <ul>
    {items_html}
  </ul>
</body>
</html>
"""


def _render_building(building: dict[str, Any]) -> str:
    layout_types = building["layout_types"]
    layout_text = "、".join(layout_types) if layout_types else "—"
    rent_text = _format_range(building["rent_min"], building["rent_max"], "円")
    area_text = _format_range(building["area_min"], building["area_max"], "㎡")
    move_in_text = _format_range(building["move_in_min"], building["move_in_max"], "")
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>{html.escape(building["name"])} | 建物マップ</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;max-width:920px;margin:24px auto;padding:0 16px;line-height:1.6}}
    .card{{border:1px solid #e5e7eb;border-radius:14px;padding:16px;margin:12px 0}}
    .grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
    @media (max-width:720px){{.grid{{grid-template-columns:1fr}}}}
    .muted{{color:#6b7280}}
  </style>
</head>
<body>
  <h1>{html.escape(building["name"])}</h1>
  <p class="muted">{html.escape(building["address"] or "")}</p>
  <div class="card">
    <div class="grid">
      <div><b>空室</b>：{html.escape(building["vacancy_status"])}</div>
      <div><b>最終更新日時</b>：{html.escape(building["last_updated"])}</div>
      <div><b>家賃レンジ</b>：{html.escape(rent_text)}</div>
      <div><b>面積レンジ</b>：{html.escape(area_text)}</div>
      <div><b>間取りタイプ</b>：{html.escape(layout_text)}</div>
      <div><b>入居可能日</b>：{html.escape(move_in_text)}</div>
    </div>
  </div>
</body>
</html>
"""


def build_static_site(output_dir: str | Path = "dist") -> Path:
    init_db()
    engine = get_engine()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    buildings_path = output_path / "b"
    buildings_path.mkdir(parents=True, exist_ok=True)

    with engine.begin() as conn:
        table_exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='building_summaries'")
        ).first()
        if table_exists is None:
            raise RuntimeError("building_summaries table not found")

        count = conn.execute(text("SELECT COUNT(*) AS count FROM building_summaries")).scalar_one()
        if count == 0:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                text(
                    """
                    INSERT INTO building_summaries (
                        building_key,
                        name,
                        address,
                        vacancy_status,
                        listings_count,
                        layout_types_json,
                        rent_min,
                        rent_max,
                        area_min,
                        area_max,
                        move_in_min,
                        move_in_max,
                        last_updated,
                        lat,
                        lon
                    ) VALUES (
                        :building_key,
                        :name,
                        :address,
                        :vacancy_status,
                        :listings_count,
                        :layout_types_json,
                        :rent_min,
                        :rent_max,
                        :area_min,
                        :area_max,
                        :move_in_min,
                        :move_in_max,
                        :last_updated,
                        :lat,
                        :lon
                    )
                    """
                ),
                {
                    "building_key": "sample-static",
                    "name": "サンプル建物",
                    "address": "東京都新宿区1-2-3",
                    "vacancy_status": "空室あり",
                    "listings_count": 1,
                    "layout_types_json": json.dumps(["1K"]),
                    "rent_min": 52000,
                    "rent_max": 68000,
                    "area_min": 20.5,
                    "area_max": 28.3,
                    "move_in_min": "即入居",
                    "move_in_max": "要相談",
                    "last_updated": now,
                    "lat": 35.6900,
                    "lon": 139.7000,
                },
            )

        rows = conn.execute(
            text(
                """
                SELECT
                    building_key,
                    name,
                    address,
                    vacancy_status,
                    listings_count,
                    layout_types_json,
                    COALESCE(rent_min, rent_yen_min) AS rent_min,
                    COALESCE(rent_max, rent_yen_max) AS rent_max,
                    COALESCE(area_min, area_sqm_min) AS area_min,
                    COALESCE(area_max, area_sqm_max) AS area_max,
                    move_in_min,
                    move_in_max,
                    last_updated,
                    lat,
                    lon
                FROM building_summaries
                ORDER BY last_updated DESC
                """
            )
        ).mappings().all()

    buildings: list[dict[str, Any]] = []
    for row in rows:
        building_key = row["building_key"]
        _ensure_building_key(building_key)
        vacancy_status = _normalize_vacancy_status(row["vacancy_status"])
        last_updated = row["last_updated"]
        if not last_updated:
            raise ValueError(f"last_updated is required for {building_key}")
        building = {
            "building_key": building_key,
            "name": row["name"],
            "address": row["address"],
            "vacancy_status": vacancy_status,
            "listings_count": row["listings_count"],
            "layout_types": _parse_layout_types(row["layout_types_json"]),
            "rent_min": row["rent_min"],
            "rent_max": row["rent_max"],
            "area_min": row["area_min"],
            "area_max": row["area_max"],
            "move_in_min": row["move_in_min"],
            "move_in_max": row["move_in_max"],
            "last_updated": str(last_updated),
        }
        page_html = _render_building(building)
        _assert_safe_html(page_html, f"building {building_key}")
        (buildings_path / f"{building_key}.html").write_text(page_html, encoding="utf-8")
        buildings.append(building)

    index_html = _render_index(buildings)
    _assert_safe_html(index_html, "index")
    (output_path / "index.html").write_text(index_html, encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate static HTML for Tatemono Map.")
    parser.add_argument(
        "--output-dir",
        default="dist",
        help="Output directory for static HTML (default: dist)",
    )
    args = parser.parse_args(argv)
    build_static_site(args.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
