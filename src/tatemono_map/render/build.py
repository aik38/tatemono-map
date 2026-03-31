from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus
from xml.sax.saxutils import escape

from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape

from tatemono_map.db.repo import connect
from tatemono_map.util.building_age import age_years_from_built_year_month

FORBIDDEN_PATTERNS = (
    r"mail=",
    r"link_id=",
    r"参照元URL",
    r"管理会社",
    r"電話",
    r"号室"
)

ROOM_SUFFIX_RE = re.compile(r"(?:\s|　)*(?:\d+|[0-9０-９]+)\s*号室")
DEFAULT_LINE_UNIVERSAL_URL = "https://lin.ee/Y0NvwKe"
DEFAULT_LINE_DEEP_LINK = "line://ti/p/@055wdvuq"
DEFAULT_BASE_PATH = "/tatemono-map"
DEFAULT_GOOGLE_SITE_VERIFICATION = "JCW5x0Dh0VamrnKUfDq10VrBt27IDc0ceuWccjjpaUo"
DEFAULT_SITE_ORIGIN = "https://www.tatemono-map.com"
KOKURAKITA_AREA_PATH = "/area/fukuoka/kitakyushu/kokurakita/"
DEFAULT_STATIC_BUILDING_LINK_LIMIT = 80
AREA_PAGE_SPECS = (
    {"label": "小倉北区", "path": KOKURAKITA_AREA_PATH, "match_tokens": ("北九州市小倉北区",), "is_major": True},
    {"label": "小倉南区", "path": "/area/fukuoka/kitakyushu/kokuraminami/", "match_tokens": ("北九州市小倉南区",), "is_major": True},
    {"label": "八幡東区", "path": "/area/fukuoka/kitakyushu/yahatahigashi/", "match_tokens": ("北九州市八幡東区",), "is_major": True},
    {"label": "八幡西区", "path": "/area/fukuoka/kitakyushu/yahatanishi/", "match_tokens": ("北九州市八幡西区",), "is_major": True},
    {"label": "若松区", "path": "/area/fukuoka/kitakyushu/wakamatsu/", "match_tokens": ("北九州市若松区",), "is_major": True},
    {"label": "戸畑区", "path": "/area/fukuoka/kitakyushu/tobata/", "match_tokens": ("北九州市戸畑区",), "is_major": True},
    {"label": "門司区", "path": "/area/fukuoka/kitakyushu/moji/", "match_tokens": ("北九州市門司区",), "is_major": True},
    {"label": "中間市", "path": "/area/fukuoka/chikuho/nakama/", "match_tokens": ("中間市",), "is_major": False},
    {"label": "遠賀郡", "path": "/area/fukuoka/chikuho/onga-gun/", "match_tokens": ("遠賀郡",), "is_major": False},
    {"label": "京都郡", "path": "/area/fukuoka/keichiku/miyako-gun/", "match_tokens": ("京都郡",), "is_major": False},
    {"label": "行橋市", "path": "/area/fukuoka/keichiku/yukuhashi/", "match_tokens": ("行橋市",), "is_major": False},
    {"label": "築上郡", "path": "/area/fukuoka/keichiku/chikujo-gun/", "match_tokens": ("築上郡",), "is_major": False},
    {"label": "豊前市", "path": "/area/fukuoka/keichiku/buzen/", "match_tokens": ("豊前市",), "is_major": False},
    {"label": "直方市", "path": "/area/fukuoka/chikuho/nogata/", "match_tokens": ("直方市",), "is_major": False},
    {"label": "鞍手郡", "path": "/area/fukuoka/chikuho/kurate-gun/", "match_tokens": ("鞍手郡",), "is_major": False},
    {"label": "田川郡", "path": "/area/fukuoka/chikuho/tagawa-gun/", "match_tokens": ("田川郡",), "is_major": False},
    {"label": "田川市", "path": "/area/fukuoka/chikuho/tagawa/", "match_tokens": ("田川市",), "is_major": False},
    {"label": "宗像市", "path": "/area/fukuoka/chikuzen/munakata/", "match_tokens": ("宗像市",), "is_major": False},
    {"label": "宮若市", "path": "/area/fukuoka/chikuho/miyawaka/", "match_tokens": ("宮若市",), "is_major": False},
    {"label": "飯塚市", "path": "/area/fukuoka/chikuho/iizuka/", "match_tokens": ("飯塚市",), "is_major": False},
    {"label": "嘉穂郡", "path": "/area/fukuoka/chikuho/kaho-gun/", "match_tokens": ("嘉穂郡",), "is_major": False},
    {"label": "嘉麻市", "path": "/area/fukuoka/chikuho/kama/", "match_tokens": ("嘉麻市",), "is_major": False},
)


def _format_yen(value: object) -> str:
    if value is None:
        return "—"
    try:
        return f"{int(float(str(value).strip().replace(',', ''))):,}"
    except (TypeError, ValueError):
        return "—"


def _sanitize_text(value: str) -> str:
    sanitized = ROOM_SUFFIX_RE.sub("", value)
    return re.sub(r"\s{2,}", " ", sanitized).strip()


def _sanitize_building(building: dict) -> dict:
    sanitized = dict(building)
    for key, value in sanitized.items():
        if isinstance(value, str):
            sanitized[key] = _sanitize_text(value)
        elif isinstance(value, list):
            sanitized[key] = [_sanitize_text(item) if isinstance(item, str) else item for item in value]
    return sanitized


def _normalize_json_scalar(value: object) -> object:
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return value


def _stable_sort_payload(payload: list[dict]) -> list[dict]:
    return sorted(payload, key=lambda row: str(row.get("id") or ""))


def _validate_public_dist(output_dir: Path) -> None:
    for html_path in output_dir.rglob("*.html"):
        content = html_path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_PATTERNS:
            if re.search(pattern, content, flags=re.IGNORECASE):
                raise RuntimeError(f"forbidden data detected in dist: {html_path} pattern={pattern}")


def _parse_date(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    normalized = text.replace("年", "/").replace("月", "/").replace("日", "")
    normalized = re.sub(r"\s+", " ", normalized)

    candidates = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m",
        "%Y/%m",
    )
    for fmt in candidates:
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue

    match = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", normalized)
    if not match:
        return None
    try:
        year, month, day = (int(match.group(i)) for i in (1, 2, 3))
        return datetime(year, month, day)
    except ValueError:
        return None


def _build_summary_date(building: dict) -> datetime | None:
    return _parse_date(building.get("last_updated")) or _parse_date(building.get("updated_at"))


def _apply_built_age_guard(building: dict) -> dict:
    guarded = dict(building)
    derived_age = age_years_from_built_year_month(guarded.get("building_built_year_month"))
    if derived_age is None:
        derived_age = guarded.get("building_built_age_years")
    guarded["building_built_age_years"] = derived_age
    guarded["derived_built_age_years"] = derived_age
    return guarded


def _build_google_maps_url(address: object) -> str | None:
    text = str(address or "").strip()
    if not text:
        return None
    return f"https://maps.google.com/?q={quote_plus(text)}"


def _build_google_maps_embed_url(address: object, api_key: str) -> str | None:
    text = str(address or "").strip()
    key = api_key.strip()
    if not text or not key:
        return None
    return f"https://www.google.com/maps/embed/v1/place?key={quote_plus(key)}&q={quote_plus(text)}"


def _normalize_base_path(base_path: str) -> str:
    normalized = base_path.strip()
    if normalized in ("", "/"):
        return ""
    normalized = normalized.rstrip("/")
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


def _slugify_building_name(name: object) -> str:
    text = unicodedata.normalize("NFKC", str(name or "")).strip().lower()
    if not text:
        return ""
    text = re.sub(r"[\s_/]+", "-", text)
    text = re.sub(r"[^\w\u3040-\u30ff\u3400-\u9fff-]", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text


def _build_detail_filename(building: dict) -> str:
    stable_id = str(building.get("building_key") or "").strip()
    slug = _slugify_building_name(building.get("name"))
    if not stable_id:
        return ""
    if not slug:
        return f"{stable_id}.html"
    return f"{slug}-{stable_id}.html"


def _render_legacy_redirect_stub(*, canonical_url: str, target_path: str, target_label: str) -> str:
    escaped_canonical = escape(canonical_url)
    escaped_target = escape(target_path)
    escaped_label = escape(target_label)
    return "\n".join(
        (
            "<!doctype html>",
            '<html lang="ja">',
            "<head>",
            '  <meta charset="utf-8">',
            '  <meta name="viewport" content="width=device-width, initial-scale=1">',
            f"  <title>{escaped_label}へ移動しました | 建物マップ</title>",
            f'  <link rel="canonical" href="{escaped_canonical}">',
            f'  <meta http-equiv="refresh" content="0; url={escaped_target}">',
            "</head>",
            "<body>",
            "  <main>",
            "    <p>ページを移動しました。</p>",
            f'    <p><a href="{escaped_target}">{escaped_label}はこちら</a></p>',
            "  </main>",
            "  <script>",
            f'    window.location.replace("{escaped_target}");',
            "  </script>",
            "</body>",
            "</html>",
            "",
        )
    )


def _write_favicon_assets(output_dir: Path, *, base_path: str) -> None:
    favicon_dir = output_dir / "assets" / "favicon"
    favicon_dir.mkdir(parents=True, exist_ok=True)

    for icon_name in ("favicon.png", "favicon-192.png", "favicon-512.png"):
        shutil.copy2(Path("assets") / "favicon" / icon_name, favicon_dir / icon_name)

    manifest_template = Path("assets/favicon/site.webmanifest").read_text(encoding="utf-8")
    rendered_manifest = manifest_template.replace("__BASE_PATH__", base_path)
    (favicon_dir / "site.webmanifest").write_text(rendered_manifest, encoding="utf-8")




def _resolve_site_origin() -> str:
    primary = os.getenv("TATEMONO_MAP_SITE_ORIGIN", "").strip()
    if primary:
        return primary
    legacy = os.getenv("TATEMONO_MAP_SITE_URL", "").strip()
    if legacy:
        return legacy
    return DEFAULT_SITE_ORIGIN

def _build_canonical_url(site_origin: str, base_path: str, page_path: str) -> str:
    origin = site_origin.strip().rstrip("/")
    prefix = _normalize_base_path(base_path)
    suffix = page_path if page_path.startswith("/") else f"/{page_path}"
    return f"{origin}{prefix}{suffix}"


def _build_sitemap_xml(*, site_origin: str, base_path: str, buildings: list[dict], area_paths: list[str]) -> str:
    urls = [
        _build_canonical_url(site_origin, base_path, "/"),
    ]
    urls.extend(_build_canonical_url(site_origin, base_path, path) for path in area_paths)
    building_urls = [_build_canonical_url(site_origin, base_path, f"/b/{b['detail_filename']}") for b in buildings]
    urls.extend(sorted(building_urls))

    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url in urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(url)}</loc>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def _write_sitemap(output_dir: Path, *, site_origin: str, base_path: str, buildings: list[dict], area_paths: list[str]) -> None:
    sitemap_xml = _build_sitemap_xml(site_origin=site_origin, base_path=base_path, buildings=buildings, area_paths=area_paths)
    (output_dir / "sitemap.xml").write_text(sitemap_xml, encoding="utf-8")


def _build_robots_txt(*, site_origin: str, base_path: str) -> str:
    sitemap_url = _build_canonical_url(site_origin, base_path, "/sitemap.xml")
    return "\n".join(
        (
            "User-agent: *",
            "Allow: /",
            f"Sitemap: {sitemap_url}",
            "",
        )
    )


def _write_robots_txt(output_dir: Path, *, site_origin: str, base_path: str) -> None:
    robots_txt = _build_robots_txt(site_origin=site_origin, base_path=base_path)
    (output_dir / "robots.txt").write_text(robots_txt, encoding="utf-8")


def _normalize_address_for_area(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", "", text)


def _resolve_area_spec(address: object) -> dict | None:
    normalized = _normalize_address_for_area(address)
    if not normalized:
        return None
    for spec in AREA_PAGE_SPECS:
        if any(token in normalized for token in spec["match_tokens"]):
            return spec
    return None


def _extract_area_label(address: object) -> str:
    matched = _resolve_area_spec(address)
    if matched:
        return str(matched["label"])
    text = str(address or "").strip()
    municipality_match = re.search(r"(北九州市[^\d\-ー丁目番地\s]*区|[^\d\-ー丁目番地\s]*(?:市|郡[^\d\-ー丁目番地\s]*(?:町|村)|町|村))", text)
    if municipality_match:
        return municipality_match.group(1)
    return "対象エリア外"


def _build_area_link(area_spec: dict, *, base_path: str) -> dict:
    return {
        "label": area_spec["label"],
        "href": f"{base_path}{area_spec['path']}",
        "path": area_spec["path"],
    }


def _extract_kitakyushu_ward_key(address: object) -> str | None:
    normalized = _normalize_address_for_area(address)
    if not normalized:
        return None
    match = re.search(r"北九州市([^\d\-ー丁目番地\s]*区)", normalized)
    if not match:
        return None
    return f"北九州市{match.group(1)}"


def _extract_kitakyushu_town_key(address: object) -> str | None:
    normalized = _normalize_address_for_area(address)
    if not normalized:
        return None
    match = re.search(r"北九州市[^\d\-ー丁目番地\s]*区([^\d０-９\-ー丁目番地\s]+)", normalized)
    if not match:
        return None
    town = match.group(1)
    if town.startswith("大字") and len(town) > 2:
        town = town[2:]
    return town or None


def _build_related_buildings(buildings: list[dict], current: dict, *, max_items: int = 8) -> list[dict]:
    current_key = current.get("building_key")
    current_address = current.get("address")
    current_ward = _extract_kitakyushu_ward_key(current_address)
    current_town = _extract_kitakyushu_town_key(current_address)

    def _sort_related(rows: list[dict]) -> list[dict]:
        rows.sort(key=lambda row: row.get("updated_epoch") or -1, reverse=True)
        return rows[:max_items]

    if current_ward:
        same_ward: list[dict] = []
        same_town: list[dict] = []
        for b in buildings:
            if b.get("building_key") == current_key:
                continue
            if _extract_kitakyushu_ward_key(b.get("address")) != current_ward:
                continue
            same_ward.append(b)
            if current_town and _extract_kitakyushu_town_key(b.get("address")) == current_town:
                same_town.append(b)

        if current_town:
            same_town_sorted = _sort_related(same_town)
            if len(same_town_sorted) >= max_items:
                return same_town_sorted

            seen = {row.get("building_key") for row in same_town_sorted}
            ward_fallback = _sort_related([row for row in same_ward if row.get("building_key") not in seen])
            return (same_town_sorted + ward_fallback)[:max_items]

        return _sort_related(same_ward)

    current_area = _resolve_area_spec(current_address)
    if current_area is None:
        return []
    related = [
        b for b in buildings
        if b.get("building_key") != current_key and _resolve_area_spec(b.get("address")) == current_area
    ]
    return _sort_related(related)


def _format_range(min_value: object, max_value: object, suffix: str) -> str | None:
    if min_value is None and max_value is None:
        return None
    if min_value is not None and max_value is not None:
        if min_value == max_value:
            return f"{min_value}{suffix}"
        return f"{min_value}{suffix}〜{max_value}{suffix}"
    if min_value is not None:
        return f"{min_value}{suffix}〜"
    return f"〜{max_value}{suffix}"


def _build_building_seo(building: dict, *, site_origin: str, base_path: str) -> dict[str, str]:
    name = str(building.get("name") or "建物詳細")
    area_label = _extract_area_label(building.get("address"))
    title = f"{name} | {area_label}の建物情報 | 建物マップ"

    address = str(building.get("address") or "").strip()
    kind = "分譲マンション" if building.get("property_kind") == "bunjo" else "建物"
    if address:
        intro = f"{name}は{address}にある{kind}です。"
    else:
        intro = f"{name}は{area_label}にある{kind}です。"

    facts: list[str] = []
    vacancy_count = building.get("sale_listing_count") if building.get("property_kind") == "bunjo" else building.get("vacancy_count")
    if vacancy_count is not None:
        facts.append(f"現在の{'販売情報' if building.get('property_kind') == 'bunjo' else '空室数'}は{vacancy_count}件")

    rent_range = _format_range(_format_yen(building.get("rent_yen_min")) if building.get("rent_yen_min") is not None else None,
                              _format_yen(building.get("rent_yen_max")) if building.get("rent_yen_max") is not None else None,
                              "円")
    if rent_range and building.get("property_kind") != "bunjo":
        facts.append(f"家賃帯は{rent_range}")

    area_range = _format_range(building.get("area_sqm_min"), building.get("area_sqm_max"), "㎡")
    if area_range:
        facts.append(f"面積帯は{area_range}")

    structure = building.get("building_structure") or building.get("structure")
    if structure:
        facts.append(f"構造は{structure}")

    built = building.get("building_built_year_month")
    if built:
        facts.append(f"築年月は{built}")
    elif building.get("building_built_age_years") is not None:
        facts.append(f"築{building.get('building_built_age_years')}年")

    layout_types = building.get("layout_types") or []
    if layout_types:
        facts.append(f"間取りタイプは{', '.join(layout_types[:3])}")

    detail_sentence = f"{'、'.join(facts)}。" if facts else "募集状況は随時更新されています。"
    description = f"{intro}{detail_sentence}建物ごとの募集状況をまとめて確認できます。"

    canonical_url = _build_canonical_url(site_origin, base_path, f"/b/{building['detail_filename']}")
    return {
        "page_title": title,
        "page_description": description,
        "canonical_url": canonical_url,
    }


def _load_buildings(db_path: str) -> tuple[list[dict], int, int, int, int]:
    conn = connect(db_path)
    canonical_buildings_count = conn.execute("SELECT COUNT(*) FROM buildings WHERE COALESCE(hidden_from_public, 0) = 0").fetchone()[0]
    summary_buildings_count = conn.execute(
        """
        SELECT COUNT(DISTINCT s.building_key)
        FROM building_summaries s
        LEFT JOIN buildings b ON b.building_id = s.building_key
        WHERE COALESCE(b.hidden_from_public, 0) = 0
        """
    ).fetchone()[0]
    buildings_count = canonical_buildings_count
    vacancy_total = conn.execute(
        """
        SELECT COALESCE(SUM(s.vacancy_count), 0)
        FROM building_summaries s
        LEFT JOIN buildings b ON b.building_id = s.building_key
        WHERE COALESCE(b.hidden_from_public, 0) = 0
        """
    ).fetchone()[0]
    buildings = conn.execute(
        """
        SELECT
            COALESCE(b.building_id, s.building_key) AS building_key,
            COALESCE(b.canonical_name, s.name, s.raw_name) AS name,
            COALESCE(b.canonical_name, s.raw_name) AS raw_name,
            COALESCE(b.canonical_address, s.address) AS address,
            s.rent_yen_min,
            s.rent_yen_max,
            s.sale_price_yen_min,
            s.sale_price_yen_max,
            s.sale_price_yen_avg,
            s.area_sqm_min,
            s.area_sqm_max,
            s.sale_area_sqm_min,
            s.sale_area_sqm_max,
            s.layout_types_json,
            s.sale_layout_types_json,
            s.property_kind,
            s.move_in_dates_json,
            s.age_years,
            s.structure,
            s.building_built_year_month,
            s.building_built_age_years,
            s.building_structure,
            s.building_availability_label,
            COALESCE(s.vacancy_count, 0) AS vacancy_count,
            s.sale_listing_count,
            s.last_updated,
            COALESCE(s.updated_at, b.updated_at) AS updated_at
        FROM building_summaries s
        LEFT JOIN buildings b ON b.building_id = s.building_key
        WHERE COALESCE(b.hidden_from_public, 0) = 0
        UNION ALL
        SELECT
            b.building_id AS building_key,
            b.canonical_name AS name,
            b.canonical_name AS raw_name,
            b.canonical_address AS address,
            NULL AS rent_yen_min,
            NULL AS rent_yen_max,
            NULL AS sale_price_yen_min,
            NULL AS sale_price_yen_max,
            NULL AS sale_price_yen_avg,
            NULL AS area_sqm_min,
            NULL AS area_sqm_max,
            NULL AS sale_area_sqm_min,
            NULL AS sale_area_sqm_max,
            NULL AS layout_types_json,
            NULL AS sale_layout_types_json,
            '' AS property_kind,
            NULL AS move_in_dates_json,
            NULL AS age_years,
            NULL AS structure,
            NULL AS building_built_year_month,
            NULL AS building_built_age_years,
            NULL AS building_structure,
            NULL AS building_availability_label,
            0 AS vacancy_count,
            NULL AS sale_listing_count,
            NULL AS last_updated,
            b.updated_at AS updated_at
        FROM buildings b
        WHERE COALESCE(b.hidden_from_public, 0) = 0
          AND NOT EXISTS (SELECT 1 FROM building_summaries s WHERE s.building_key = b.building_id)
        ORDER BY updated_at DESC
        """
    ).fetchall()

    building_list = []
    for row in buildings:
        building = dict(row)
        building["layout_types"] = json.loads(building.get("layout_types_json") or "[]")
        building["move_in_dates"] = json.loads(building.get("move_in_dates_json") or "[]")
        summary_date = _build_summary_date(building)
        building["updated_epoch"] = int(summary_date.timestamp()) if summary_date else -1
        building_list.append(_sanitize_building(_apply_built_age_guard(building)))
    conn.close()
    print(
        "render_kpi_counts canonical_buildings_count={} summary_buildings_count={} vacancy_total={}".format(
            canonical_buildings_count,
            summary_buildings_count,
            vacancy_total,
        )
    )
    return building_list, canonical_buildings_count, summary_buildings_count, buildings_count, vacancy_total


def _build_buildings_payload(buildings: list[dict]) -> list[dict]:
    payload = []
    for b in buildings:
        payload.append(
            {
                "id": b.get("building_key"),
                "detail_filename": b.get("detail_filename"),
                "name": b.get("name"),
                "address": b.get("address"),
                "vacancy_count": b.get("vacancy_count"),
                "rent_min": b.get("rent_yen_min"),
                "rent_max": b.get("rent_yen_max"),
                "sale_price_min": b.get("sale_price_yen_min"),
                "sale_price_max": b.get("sale_price_yen_max"),
                "sale_price_avg": b.get("sale_price_yen_avg"),
                "area_min": b.get("area_sqm_min"),
                "area_max": b.get("area_sqm_max"),
                "sale_area_min": b.get("sale_area_sqm_min"),
                "sale_area_max": b.get("sale_area_sqm_max"),
                "updated_at": b.get("last_updated") or b.get("updated_at"),
                "updated_epoch": b.get("updated_epoch"),
                "google_maps_url": _build_google_maps_url(b.get("address")),
                "room_types": b.get("layout_types") or [],
                "sale_layout_types": json.loads(b.get("sale_layout_types_json")) if b.get("sale_layout_types_json") else [],
                "property_kind": b.get("property_kind") or "",
                "sale_listing_count": b.get("sale_listing_count"),
                "structure": b.get("structure"),
                "built_year": b.get("age_years"),
                "building_structure": b.get("building_structure") or b.get("structure"),
                "building_built_year_month": b.get("building_built_year_month"),
                "building_built_age_years": b.get("derived_built_age_years") if b.get("derived_built_age_years") is not None else b.get("age_years"),
                "building_availability_label": b.get("building_availability_label"),
            }
        )
    normalized = []
    for row in payload:
        normalized.append({key: _normalize_json_scalar(value) for key, value in row.items()})
    return _stable_sort_payload(normalized)


def _build_buildings_v2_min_payload(buildings: list[dict]) -> list[dict]:
    payload = []
    for b in buildings:
        payload.append(
            {
                "id": b.get("building_key"),
                "detail_filename": b.get("detail_filename"),
                "name": b.get("name"),
                "address": b.get("address"),
                "vacancy_count": b.get("vacancy_count"),
                "rent_min": b.get("rent_yen_min"),
                "rent_max": b.get("rent_yen_max"),
                "sale_price_min": b.get("sale_price_yen_min"),
                "sale_price_max": b.get("sale_price_yen_max"),
                "sale_price_avg": b.get("sale_price_yen_avg"),
                "area_min": b.get("area_sqm_min"),
                "area_max": b.get("area_sqm_max"),
                "sale_area_min": b.get("sale_area_sqm_min"),
                "sale_area_max": b.get("sale_area_sqm_max"),
                "updated_at": b.get("last_updated") or b.get("updated_at"),
                "updated_epoch": b.get("updated_epoch"),
                "property_kind": b.get("property_kind") or "",
                "sale_listing_count": b.get("sale_listing_count"),
                "building_structure": b.get("building_structure") or b.get("structure"),
                "building_availability_label": b.get("building_availability_label"),
                "building_built_year_month": b.get("building_built_year_month"),
                "building_built_age_years": b.get("derived_built_age_years") if b.get("derived_built_age_years") is not None else b.get("age_years"),
            }
        )
    normalized = []
    for row in payload:
        normalized.append({key: _normalize_json_scalar(value) for key, value in row.items()})
    return _stable_sort_payload(normalized)


def export_buildings_json(db_path: str, output_path: str, fmt: str) -> int:
    buildings, *_ = _load_buildings(db_path)
    if fmt == "legacy":
        payload = _build_buildings_payload(buildings)
    elif fmt == "v2min":
        payload = _build_buildings_v2_min_payload(buildings)
    else:
        raise ValueError(f"unsupported format: {fmt}")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"export_buildings_json path={out} format={fmt} count={len(payload)} bytes={out.stat().st_size}")
    return len(payload)


def _write_build_info(output_dir: Path, *, db_path: str, buildings_count_json: int) -> None:
    conn = connect(db_path)
    try:
        buildings_count_db = conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
        vacancies_count_db = conn.execute(
            "SELECT COALESCE(SUM(vacancy_count), 0) FROM building_summaries"
        ).fetchone()[0]
    finally:
        conn.close()

    build_info = {
        "git_sha": os.getenv("GITHUB_SHA") or os.getenv("TATEMONO_MAP_GIT_SHA") or "unknown",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "buildings_count_json": buildings_count_json,
        "buildings_count_db": buildings_count_db,
        "vacancies_count_db": vacancies_count_db,
    }
    build_info_path = output_dir / "build_info.json"
    build_info_path.write_text(
        json.dumps(build_info, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8"
    )
    print(f"build_info_json path={build_info_path} payload={json.dumps(build_info, ensure_ascii=False)}")


def _write_buildings_json(output_dir: Path, buildings: list[dict]) -> None:
    payload = _build_buildings_payload(buildings)
    payload_v2_min = _build_buildings_v2_min_payload(buildings)

    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    buildings_path = data_dir / "buildings.json"
    buildings_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    buildings_v2_min_path = data_dir / "buildings.v2.min.json"
    buildings_v2_min_path.write_text(json.dumps(payload_v2_min, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(f"render_buildings_json path={buildings_path} bytes={buildings_path.stat().st_size} count={len(payload)}")
    print(
        f"render_buildings_json path={buildings_v2_min_path} bytes={buildings_v2_min_path.stat().st_size} count={len(payload_v2_min)}"
    )


def _build_dist_version(
    output_dir: Path,
    db_path: str,
    buildings: list[dict],
    *,
    canonical_buildings_count: int,
    summary_buildings_count: int,
    buildings_count: int,
    vacancy_total: int,
    template_root: str,
    line_cta_url: str,
    line_deep_link_url: str,
    google_maps_embed_api_key: str,
    base_path: str,
    google_site_verification: str,
    site_origin: str,
) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    (output_dir / "b").mkdir(parents=True, exist_ok=True)

    env = Environment(loader=FileSystemLoader(template_root), autoescape=select_autoescape(["html"]))
    env.filters["yen"] = _format_yen
    index_tpl = env.get_template("index.html.j2")
    building_tpl = env.get_template("building.html.j2")
    area_tpl = env.get_template("area.html.j2")

    total_buildings = len(buildings)
    for b in buildings:
        b["detail_filename"] = _build_detail_filename(b)
        b["legacy_detail_filename"] = f"{b['building_key']}.html"
    total_vacant = sum((b.get("vacancy_count") or 0) for b in buildings)
    parsed_dates = [parsed for parsed in (_build_summary_date(b) for b in buildings) if parsed is not None]
    latest_data_date = max(parsed_dates, default=None)
    latest_data_date_label = latest_data_date.strftime("%Y/%m/%d") if latest_data_date else "—"
    area_buildings_map = {spec["path"]: [] for spec in AREA_PAGE_SPECS}
    for building in buildings:
        matched_area = _resolve_area_spec(building.get("address"))
        if matched_area:
            area_buildings_map[matched_area["path"]].append(building)
    major_area_links = [_build_area_link(spec, base_path=base_path) for spec in AREA_PAGE_SPECS if spec["is_major"]]
    all_area_links = [_build_area_link(spec, base_path=base_path) for spec in AREA_PAGE_SPECS]
    area_hub_links = {
        spec["label"]: {"label": spec["label"], "href": f"{base_path}{spec['path']}"}
        for spec in AREA_PAGE_SPECS
    }

    (output_dir / "index.html").write_text(
        index_tpl.render(
            buildings=buildings,
            static_building_links=buildings[:DEFAULT_STATIC_BUILDING_LINK_LIMIT],
            total_buildings=total_buildings,
            total_vacant=total_vacant,
            total_buildings_formatted=f"{total_buildings:,}",
            total_vacant_formatted=f"{total_vacant:,}",
            canonical_buildings_count=canonical_buildings_count,
            summary_buildings_count=summary_buildings_count,
            canonical_buildings_count_formatted=f"{canonical_buildings_count:,}",
            summary_buildings_count_formatted=f"{summary_buildings_count:,}",
            buildings_count=buildings_count,
            buildings_count_formatted=f"{buildings_count:,}",
            vacancy_total=vacancy_total,
            vacancy_total_formatted=f"{vacancy_total:,}",
            latest_data_date=latest_data_date_label,
            page_title="北九州の賃貸・建物データベース | 建物マップ",
            page_description="北九州のマンション・アパートを建物単位で検索できる建物データベース。建物名、住所、空室数、家賃帯、面積帯などをまとめて確認できます。",
            canonical_url=_build_canonical_url(site_origin, base_path, "/"),
            major_area_links=major_area_links,
            all_area_links=all_area_links,
            area_hub_links=area_hub_links,
            base_path=base_path,
            google_site_verification=google_site_verification,
        ),
        encoding="utf-8",
    )

    for area_spec in AREA_PAGE_SPECS:
        area_dir = output_dir / area_spec["path"].strip("/")
        area_dir.mkdir(parents=True, exist_ok=True)
        area_name = area_spec["label"]
        area_dir.joinpath("index.html").write_text(
            area_tpl.render(
                area_name=area_name,
                intro_text=f"{area_name}にある建物をまとめて確認できます。気になる建物があればLINEで最新情報をご相談ください。",
                buildings=area_buildings_map[area_spec["path"]],
                page_title=f"{area_name}の建物一覧 | 建物マップ",
                page_description=f"{area_name}のマンション・アパートを建物単位で確認できる一覧ページです。住所、空室数、家賃帯、面積帯をまとめてチェックできます。",
                canonical_url=_build_canonical_url(site_origin, base_path, area_spec["path"]),
                line_cta_url=line_cta_url,
                line_deep_link_url=line_deep_link_url,
                base_path=base_path,
                google_site_verification=google_site_verification,
            ),
            encoding="utf-8",
        )

    for b in buildings:
        maps_url = _build_google_maps_url(b.get("address"))
        maps_embed_url = _build_google_maps_embed_url(b.get("address"), google_maps_embed_api_key)
        seo = _build_building_seo(b, site_origin=site_origin, base_path=base_path)
        detail_path = f"{base_path}/b/{b['detail_filename']}"
        area_hub = None
        area_spec = _resolve_area_spec(b.get("address"))
        if area_spec:
            area_hub = {
                "name": area_spec["label"],
                "url": f"{base_path}{area_spec['path']}",
            }
        html = building_tpl.render(
            building=b,
            maps_url=maps_url,
            maps_embed_url=maps_embed_url,
            line_cta_url=line_cta_url,
            line_deep_link_url=line_deep_link_url,
            area_hub=area_hub,
            related_buildings=_build_related_buildings(buildings, b, max_items=8),
            page_title=seo["page_title"],
            page_description=seo["page_description"],
            canonical_url=seo["canonical_url"],
            base_path=base_path,
            google_site_verification=google_site_verification,
        )
        (output_dir / "b" / b["detail_filename"]).write_text(html, encoding="utf-8")
        if b["detail_filename"] != b["legacy_detail_filename"]:
            legacy_stub = _render_legacy_redirect_stub(
                canonical_url=seo["canonical_url"],
                target_path=detail_path,
                target_label=str(b.get("name") or "建物詳細"),
            )
            (output_dir / "b" / b["legacy_detail_filename"]).write_text(legacy_stub, encoding="utf-8")

    _write_favicon_assets(output_dir, base_path=base_path)
    _write_buildings_json(output_dir, buildings)
    _write_sitemap(
        output_dir,
        site_origin=site_origin,
        base_path=base_path,
        buildings=buildings,
        area_paths=[spec["path"] for spec in AREA_PAGE_SPECS],
    )
    _write_robots_txt(output_dir, site_origin=site_origin, base_path=base_path)
    _write_build_info(output_dir, db_path=db_path, buildings_count_json=len(_build_buildings_v2_min_payload(buildings)))

    (output_dir / ".nojekyll").touch()
    _validate_public_dist(output_dir)


def build_dist(db_path: str, output_dir: str, *, template_root: str = "templates", base_path: str = DEFAULT_BASE_PATH) -> None:
    load_dotenv()
    line_cta_url = os.getenv("TATEMONO_MAP_LINE_CTA_URL", DEFAULT_LINE_UNIVERSAL_URL).strip() or DEFAULT_LINE_UNIVERSAL_URL
    line_deep_link_url = os.getenv("TATEMONO_MAP_LINE_DEEP_LINK_URL", DEFAULT_LINE_DEEP_LINK).strip() or DEFAULT_LINE_DEEP_LINK
    google_maps_embed_api_key = os.getenv("TATEMONO_MAP_GOOGLE_MAPS_EMBED_API_KEY", "")
    google_site_verification = os.getenv("TATEMONO_MAP_GOOGLE_SITE_VERIFICATION", DEFAULT_GOOGLE_SITE_VERIFICATION).strip()
    site_origin = _resolve_site_origin()
    normalized_base_path = _normalize_base_path(base_path)

    buildings, canonical_buildings_count, summary_buildings_count, buildings_count, vacancy_total = _load_buildings(db_path)
    _build_dist_version(
        Path(output_dir),
        db_path,
        buildings,
        canonical_buildings_count=canonical_buildings_count,
        summary_buildings_count=summary_buildings_count,
        buildings_count=buildings_count,
        vacancy_total=vacancy_total,
        template_root=template_root,
        line_cta_url=line_cta_url,
        line_deep_link_url=line_deep_link_url,
        google_maps_embed_api_key=google_maps_embed_api_key,
        base_path=normalized_base_path,
        google_site_verification=google_site_verification,
        site_origin=site_origin,
    )


def build_dist_versions(db_path: str, output_dir: str, *, base_path: str = DEFAULT_BASE_PATH) -> None:
    load_dotenv()
    line_cta_url = os.getenv("TATEMONO_MAP_LINE_CTA_URL", DEFAULT_LINE_UNIVERSAL_URL).strip() or DEFAULT_LINE_UNIVERSAL_URL
    line_deep_link_url = os.getenv("TATEMONO_MAP_LINE_DEEP_LINK_URL", DEFAULT_LINE_DEEP_LINK).strip() or DEFAULT_LINE_DEEP_LINK
    google_maps_embed_api_key = os.getenv("TATEMONO_MAP_GOOGLE_MAPS_EMBED_API_KEY", "")
    google_site_verification = os.getenv("TATEMONO_MAP_GOOGLE_SITE_VERIFICATION", DEFAULT_GOOGLE_SITE_VERIFICATION).strip()
    site_origin = _resolve_site_origin()
    normalized_base_path = _normalize_base_path(base_path)

    out = Path(output_dir)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    buildings, canonical_buildings_count, summary_buildings_count, buildings_count, vacancy_total = _load_buildings(db_path)
    _build_dist_version(
        out,
        db_path,
        buildings,
        canonical_buildings_count=canonical_buildings_count,
        summary_buildings_count=summary_buildings_count,
        buildings_count=buildings_count,
        vacancy_total=vacancy_total,
        template_root="templates_v2",
        line_cta_url=line_cta_url,
        line_deep_link_url=line_deep_link_url,
        google_maps_embed_api_key=google_maps_embed_api_key,
        base_path=normalized_base_path,
        google_site_verification=google_site_verification,
        site_origin=site_origin,
    )
    _build_dist_version(
        out / "v1",
        db_path,
        buildings,
        canonical_buildings_count=canonical_buildings_count,
        summary_buildings_count=summary_buildings_count,
        buildings_count=buildings_count,
        vacancy_total=vacancy_total,
        template_root="templates",
        line_cta_url=line_cta_url,
        line_deep_link_url=line_deep_link_url,
        google_maps_embed_api_key=google_maps_embed_api_key,
        base_path=normalized_base_path,
        google_site_verification=google_site_verification,
        site_origin=site_origin,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="data/tatemono_map.sqlite3")
    parser.add_argument("--output-dir", default="dist")
    parser.add_argument("--version", choices=("v1", "v2", "all"), default="all")
    parser.add_argument("--base-path", default=os.getenv("TATEMONO_MAP_BASE_PATH", DEFAULT_BASE_PATH))
    args = parser.parse_args()

    if args.version == "all":
        build_dist_versions(args.db_path, args.output_dir, base_path=args.base_path)
    elif args.version == "v2":
        build_dist(args.db_path, args.output_dir, template_root="templates_v2", base_path=args.base_path)
    else:
        build_dist(args.db_path, args.output_dir, template_root="templates", base_path=args.base_path)
    print("dist generated")


if __name__ == "__main__":
    main()
