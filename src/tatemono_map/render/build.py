from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from tatemono_map.api.database import get_engine, init_db

ALLOWED_VACANCY_STATUS = {"空室あり", "満室", "不明"}
BUILDING_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
ROOM_PREFIX_PATTERN = re.compile(r"^\s*\d{1,4}\s*[:：]\s*")
ROOM_LIKE_PATTERN = re.compile(r"(?:号室|部屋番号|室番号)")

FORBIDDEN_PATTERNS = [
    re.compile(r"号室"),
    re.compile(r"参照元"),
    re.compile(r"元付"),
    re.compile(r"管理会社"),
    re.compile(r"見積"),
    re.compile(r"\.pdf\b", re.IGNORECASE),
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




def _validate_public_building_summaries(conn: Any) -> None:
    rows = conn.execute(
        text(
            """
            SELECT building_key, name
            FROM building_summaries
            WHERE name IS NOT NULL
            """
        )
    ).mappings().all()
    violations: list[str] = []
    for row in rows:
        name = str(row["name"]).strip()
        if ROOM_PREFIX_PATTERN.match(name) or ROOM_LIKE_PATTERN.search(name):
            violations.append(f"{row['building_key']}:{name}")
    if violations:
        sample = ", ".join(violations[:5])
        raise ValueError(
            "Public building_summaries contains room-like prefixes in name. "
            f"Fix normalization before build: {sample}"
        )

    duplicate_names = conn.execute(
        text(
            """
            SELECT name, COUNT(DISTINCT building_key) AS key_count
            FROM building_summaries
            WHERE name IS NOT NULL AND TRIM(name) <> ''
            GROUP BY name
            HAVING COUNT(DISTINCT building_key) > 1
            """
        )
    ).mappings().all()
    if duplicate_names:
        sample = ", ".join(
            f"{row['name']}({row['key_count']})" for row in duplicate_names[:5]
        )
        raise ValueError(
            "Duplicate building_key detected for same building name in building_summaries. "
            f"Run consolidation before build: {sample}"
        )

def _render_index(buildings: list[dict[str, Any]]) -> str:
    items = []
    for building in buildings:
        key = building["building_key"]
        name = html.escape(building["name"] or "")
        address = html.escape(building["address"] or "")
        updated = html.escape(building["last_updated"])
        items.append(
            f'<li data-name="{name.lower()}" data-address="{address.lower()}">'
            f'<a href="b/{key}.html">{name}</a> '
            f'<span class="muted">{address}</span> '
            f'<span class="muted">({updated})</span></li>'
        )
    items_html = "\n".join(items) if items else "<li>公開建物はまだありません。</li>"
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>建物一覧 | 建物マップ</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;max-width:920px;margin:24px auto;padding:0 16px;line-height:1.6}}
    .muted{{color:#6b7280;font-size:0.9em}}
    input{{padding:8px 10px;width:100%;max-width:420px;margin-bottom:12px}}
  </style>
</head>
<body>
  <h1>建物一覧</h1>
  <p>総建物数: <b id="building-count">{len(buildings)}</b></p>
  <input id="search" type="search" placeholder="建物名・住所で絞り込み" />
  <ul id="building-list">
    {items_html}
  </ul>
  <script>
    const input = document.getElementById('search');
    const list = document.getElementById('building-list');
    const items = Array.from(list.querySelectorAll('li'));
    const count = document.getElementById('building-count');
    input.addEventListener('input', () => {{
      const q = input.value.trim().toLowerCase();
      let visible = 0;
      for (const item of items) {{
        const hay = `${{item.dataset.name}} ${{item.dataset.address}}`;
        const show = q === '' || hay.includes(q);
        item.style.display = show ? '' : 'none';
        if (show) visible += 1;
      }}
      count.textContent = String(visible);
    }});
  </script>
</body>
</html>
"""


def _render_building(building: dict[str, Any]) -> str:
    layout_types = building["layout_types"]
    layout_text = "、".join(layout_types) if layout_types else "—"
    rent_text = _format_range(building["rent_min"], building["rent_max"], "円")
    area_text = _format_range(building["area_min"], building["area_max"], "㎡")
    move_in_text = _format_range(building["move_in_min"], building["move_in_max"], "")
    maps_link = ""
    if building.get("lat") is not None and building.get("lon") is not None:
        maps_url = f"https://www.google.com/maps?q={building['lat']},{building['lon']}"
        maps_link = (
            f'<div><b>地図</b>：<a href="{html.escape(maps_url)}" target="_blank" '
            'rel="noopener">Google Mapsで開く</a></div>'
        )
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
      <div><b>募集件数</b>：{building["listings_count"] or 0}</div>
      <div><b>家賃レンジ</b>：{html.escape(rent_text)}</div>
      <div><b>面積レンジ</b>：{html.escape(area_text)}</div>
      <div><b>間取りタイプ</b>：{html.escape(layout_text)}</div>
      <div><b>入居可能日</b>：{html.escape(move_in_text)}</div>
      {maps_link}
    </div>
  </div>
</body>
</html>
"""


def _resolve_site_url(site_url: str | None) -> str:
    if site_url:
        return site_url
    return os.getenv("TATEMONO_MAP_SITE_URL", "")


def _resolve_google_verification_file(filename: str | None) -> str | None:
    if filename:
        return filename
    return os.getenv("TATEMONO_MAP_GOOGLE_VERIFICATION_FILE")


def _ensure_safe_filename(filename: str) -> None:
    if "/" in filename or "\\" in filename:
        raise ValueError(f"Path separators are not allowed in verification filename: {filename}")


def _write_google_verification(output_path: Path, filename: str) -> None:
    _ensure_safe_filename(filename)
    content = f"google-site-verification: {filename}\n"
    (output_path / filename).write_text(content, encoding="utf-8")


def write_robots(output_path: Path, site_url: str) -> None:
    sitemap_url = f"{site_url.rstrip('/')}/sitemap.xml" if site_url else "/sitemap.xml"
    robots_txt = f"User-agent: *\nAllow: /\nSitemap: {sitemap_url}\n"
    (output_path / "robots.txt").write_text(robots_txt, encoding="utf-8")


def write_sitemap(output_path: Path, site_url: str, page_paths: list[str]) -> None:
    urlset = ET.Element("urlset", {"xmlns": "http://www.sitemaps.org/schemas/sitemap/0.9"})
    base_url = site_url.rstrip("/")
    for page_path in page_paths:
        normalized_path = page_path if page_path.startswith("/") else f"/{page_path}"
        loc_value = f"{base_url}{normalized_path}" if base_url else normalized_path
        url = ET.SubElement(urlset, "url")
        loc = ET.SubElement(url, "loc")
        loc.text = loc_value
    tree = ET.ElementTree(urlset)
    tree.write(output_path / "sitemap.xml", encoding="utf-8", xml_declaration=True)


def build_static_site(
    output_dir: str | Path = "dist",
    site_url: str | None = None,
    google_verification_file: str | None = None,
    private_output_dir: str | Path | None = None,
) -> Path:
    init_db()
    engine = get_engine()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    buildings_path = output_path / "b"
    buildings_path.mkdir(parents=True, exist_ok=True)
    resolved_site_url = _resolve_site_url(site_url)
    resolved_google_verification_file = _resolve_google_verification_file(google_verification_file)

    with engine.begin() as conn:
        table_exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='building_summaries'")
        ).first()
        if table_exists is None:
            raise RuntimeError("building_summaries table not found")

        _validate_public_building_summaries(conn)

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
    page_paths = ["/"]
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
            "lat": row["lat"],
            "lon": row["lon"],
        }
        page_html = _render_building(building)
        _assert_safe_html(page_html, f"building {building_key}")
        (buildings_path / f"{building_key}.html").write_text(page_html, encoding="utf-8")
        buildings.append(building)
        page_paths.append(f"/b/{building_key}.html")

    index_html = _render_index(buildings)
    _assert_safe_html(index_html, "index")
    (output_path / "index.html").write_text(index_html, encoding="utf-8")
    if private_output_dir:
        private_path = Path(private_output_dir)
        private_path.mkdir(parents=True, exist_ok=True)
        with engine.begin() as conn:
            listings_exists = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='listings'")
            ).first()
            private_rows = []
            if listings_exists is not None:
                private_rows = conn.execute(
                    text(
                        """
                        SELECT building_key, name, room_label, rent_yen, area_sqm, layout, move_in, fetched_at
                        FROM listings
                        ORDER BY fetched_at DESC
                        """
                    )
                ).mappings().all()
        table_rows = "".join(
            "<tr>"
            f"<td>{html.escape(str(row['building_key'] or ''))}</td>"
            f"<td>{html.escape(str(row['name'] or ''))}</td>"
            f"<td>{html.escape(str(row['room_label'] or ''))}</td>"
            f"<td>{html.escape(str(row['rent_yen'] or ''))}</td>"
            f"<td>{html.escape(str(row['area_sqm'] or ''))}</td>"
            f"<td>{html.escape(str(row['layout'] or ''))}</td>"
            f"<td>{html.escape(str(row['move_in'] or ''))}</td>"
            "</tr>"
            for row in private_rows
        )
        private_html = (
            "<!doctype html><html lang='ja'><head><meta charset='utf-8'><title>Private Listings</title>"
            "</head><body><h1>Private Listings</h1><table border='1'><tr>"
            "<th>building_key</th><th>name</th><th>room_label</th><th>rent_yen</th>"
            "<th>area_sqm</th><th>layout</th><th>move_in</th></tr>"
            f"{table_rows}</table></body></html>"
        )
        (private_path / "index.html").write_text(private_html, encoding="utf-8")
    write_robots(output_path, resolved_site_url)
    write_sitemap(output_path, resolved_site_url, page_paths)
    if resolved_google_verification_file:
        _write_google_verification(output_path, resolved_google_verification_file)
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate static HTML for Tatemono Map.")
    parser.add_argument(
        "--output-dir",
        default="dist",
        help="Output directory for static HTML (default: dist)",
    )
    parser.add_argument(
        "--site-url",
        default=None,
        help="Base site URL for sitemap/robots (default: TATEMONO_MAP_SITE_URL env or empty)",
    )
    parser.add_argument(
        "--google-verification-file",
        default=None,
        help="Google Search Console HTML verification filename (default: TATEMONO_MAP_GOOGLE_VERIFICATION_FILE env)",
    )
    parser.add_argument(
        "--private-output-dir",
        default=None,
        help="Optional private output directory for room-level listings (never linked from public pages)",
    )
    args = parser.parse_args(argv)
    build_static_site(
        args.output_dir,
        site_url=args.site_url,
        google_verification_file=args.google_verification_file,
        private_output_dir=args.private_output_dir,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
