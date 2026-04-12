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
ACCESS_NUMERIC_ONLY_RE = re.compile(r"^[\d０-９\s　.,，・/／\-〜~分分]+$")
DEFAULT_LINE_UNIVERSAL_URL = "https://lin.ee/Y0NvwKe"
DEFAULT_LINE_DEEP_LINK = "line://ti/p/@055wdvuq"
DEFAULT_BASE_PATH = "/tatemono-map"
DEFAULT_GOOGLE_SITE_VERIFICATION = "JCW5x0Dh0VamrnKUfDq10VrBt27IDc0ceuWccjjpaUo"
DEFAULT_SITE_ORIGIN = "https://www.tatemono-map.com"
DEFAULT_ADDRESS_MODE = "full"
DEFAULT_THEME = "ph"
KOKURAKITA_AREA_PATH = "/area/fukuoka/kitakyushu/kokurakita/"
DEFAULT_STATIC_BUILDING_LINK_LIMIT = 80
AREA_PAGE_SPECS = (
    {"label": "小倉北区", "path": KOKURAKITA_AREA_PATH, "match_tokens": ("北九州市小倉北区",), "is_major": True, "intro_text": "小倉北区の建物を建物単位で確認できる一覧ページです。小倉駅周辺の商業エリアから近郊の住宅街まで、エリア内の建物情報をまとめて見ながら、住所や募集状況を比較して探せます。"},
    {"label": "小倉南区", "path": "/area/fukuoka/kitakyushu/kokuraminami/", "match_tokens": ("北九州市小倉南区",), "is_major": True, "intro_text": "小倉南区の建物を建物単位で確認できる一覧ページです。ニュータウンやベッドタウンが広がる住宅エリアを中心に、住所や現在の募集状況を建物単位で比較しながら探せます。"},
    {"label": "八幡東区", "path": "/area/fukuoka/kitakyushu/yahatahigashi/", "match_tokens": ("北九州市八幡東区",), "is_major": True, "intro_text": "八幡東区の建物を建物単位で確認できる一覧ページです。山麓の住宅地から再開発が進む駅周辺エリアまで、建物情報をまとめて見ながら、住所や募集状況を比較して探せます。"},
    {"label": "八幡西区", "path": "/area/fukuoka/kitakyushu/yahatanishi/", "match_tokens": ("北九州市八幡西区",), "is_major": True, "intro_text": "八幡西区の建物を建物単位で確認できる一覧ページです。黒崎周辺の商業地から折尾周辺の学生街、郊外の住宅地まで、住所や募集状況を建物単位で比較しながら探せます。"},
    {"label": "若松区", "path": "/area/fukuoka/kitakyushu/wakamatsu/", "match_tokens": ("北九州市若松区",), "is_major": True, "intro_text": "若松区の建物を建物単位で確認できる一覧ページです。洞海湾沿いの市街地から北部の自然に近い住宅エリアまで、建物情報をまとめて見ながら、住所や募集状況を比較して探せます。"},
    {"label": "戸畑区", "path": "/area/fukuoka/kitakyushu/tobata/", "match_tokens": ("北九州市戸畑区",), "is_major": True, "intro_text": "戸畑区の建物を建物単位で確認できる一覧ページです。JR駅周辺の市街地と文教地区の側面を持つ住宅エリアの建物情報を、住所や募集状況ごとに比較しながら探せます。"},
    {"label": "門司区", "path": "/area/fukuoka/kitakyushu/moji/", "match_tokens": ("北九州市門司区",), "is_major": True, "intro_text": "門司区の建物を建物単位で確認できる一覧ページです。門司港周辺の商業エリアから高台の住宅地まで、エリア内の建物情報をまとめて見ながら、住所や募集状況を比較して探せます。"},
    {"label": "中間市", "path": "/area/fukuoka/chikuho/nakama/", "match_tokens": ("中間市",), "is_major": False, "intro_text": "中間市の建物を建物単位で確認できる一覧ページです。北九州市に隣接する市街地と落ち着いた住宅エリアの建物情報を、住所や募集状況を建物単位で見比べながら探せます。"},
    {"label": "遠賀郡", "path": "/area/fukuoka/chikuho/onga-gun/", "match_tokens": ("遠賀郡",), "is_major": False, "intro_text": "遠賀郡の建物を建物単位で確認できる一覧ページです。遠賀川流域から海沿いの居住エリアまで、郡内の建物情報をまとめて見ながら、住所や募集状況を比較して探せます。"},
    {"label": "京都郡", "path": "/area/fukuoka/keichiku/miyako-gun/", "match_tokens": ("京都郡",), "is_major": False, "intro_text": "京都郡の建物を建物単位で確認できる一覧ページです。臨海部の産業拠点から内陸の住宅エリアまで、エリア内の建物情報をまとめて見ながら、住所や募集状況を比較して探せます。"},
    {"label": "行橋市", "path": "/area/fukuoka/keichiku/yukuhashi/", "match_tokens": ("行橋市",), "is_major": False, "intro_text": "行橋市の建物を建物単位で確認できる一覧ページです。京築地域の中心市街地から平野部に広がる住宅地まで、建物情報をまとめて見ながら、住所や募集状況を比較して探せます。"},
    {"label": "築上郡", "path": "/area/fukuoka/keichiku/chikujo-gun/", "match_tokens": ("築上郡",), "is_major": False, "intro_text": "築上郡の建物を建物単位で確認できる一覧ページです。山々と海に囲まれた自然豊かな住環境エリアの建物情報を、住所や現在の募集状況を建物単位で比較しながら探せます。"},
    {"label": "豊前市", "path": "/area/fukuoka/keichiku/buzen/", "match_tokens": ("豊前市",), "is_major": False, "intro_text": "豊前市の建物を建物単位で確認できる一覧ページです。市役所周辺の市街地から郊外の自然に近い住宅地まで、建物情報をまとめて見ながら、住所や募集状況を比較して探せます。"},
    {"label": "直方市", "path": "/area/fukuoka/chikuho/nogata/", "match_tokens": ("直方市",), "is_major": False, "intro_text": "直方市の建物を建物単位で確認できる一覧ページです。遠賀川沿いの市街地と歴史ある旧街道周辺の住宅エリアまで、住所や募集状況を建物単位で比較しながら探せます。"},
    {"label": "鞍手郡", "path": "/area/fukuoka/chikuho/kurate-gun/", "match_tokens": ("鞍手郡",), "is_major": False, "intro_text": "鞍手郡の建物を建物単位で確認できる一覧ページです。幹線道路沿いの市街地と田園風景が広がる住宅エリアの建物情報を、住所や募集状況を見比べながら探せます。"},
    {"label": "田川郡", "path": "/area/fukuoka/chikuho/tagawa-gun/", "match_tokens": ("田川郡",), "is_major": False, "intro_text": "田川郡の建物を建物単位で確認できる一覧ページです。盆地特有の地勢を活かした住環境が広がる郡内エリアの建物情報を、住所や募集状況を建物単位で比較して探せます。"},
    {"label": "田川市", "path": "/area/fukuoka/chikuho/tagawa/", "match_tokens": ("田川市",), "is_major": False, "intro_text": "田川市の建物を建物単位で確認できる一覧ページです。中心市街地を囲むように広がる住宅・商業エリアの建物情報をまとめて見ながら、住所や募集状況を比較して探せます。"},
    {"label": "宗像市", "path": "/area/fukuoka/chikuzen/munakata/", "match_tokens": ("宗像市",), "is_major": False, "intro_text": "宗像市の建物を建物単位で確認できる一覧ページです。福岡・北九州両都市圏のベッドタウンとして広がる住宅地の建物情報を、住所や募集状況を建物単位で比較して探せます。"},
    {"label": "宮若市", "path": "/area/fukuoka/chikuho/miyawaka/", "match_tokens": ("宮若市",), "is_major": False, "intro_text": "宮若市の建物を建物単位で確認できる一覧ページです。工業拠点と自然環境が共存する住宅エリアの建物情報をまとめて見ながら、住所や募集状況を比較して探せます。"},
    {"label": "飯塚市", "path": "/area/fukuoka/chikuho/iizuka/", "match_tokens": ("飯塚市",), "is_major": False, "intro_text": "飯塚市の建物を建物単位で確認できる一覧ページです。筑豊地域の中心的な商業地と文教・住宅エリアが揃う市内の建物を、住所や募集状況ごとに比較して探せます。"},
    {"label": "嘉穂郡", "path": "/area/fukuoka/chikuho/kaho-gun/", "match_tokens": ("嘉穂郡",), "is_major": False, "intro_text": "嘉穂郡の建物を建物単位で確認できる一覧ページです。飯塚市に隣接し、自然と住宅地が調和するエリア内の建物情報をまとめて見ながら、住所や募集状況を比較して探せます。"},
    {"label": "嘉麻市", "path": "/area/fukuoka/chikuho/kama/", "match_tokens": ("嘉麻市",), "is_major": False, "intro_text": "嘉麻市の建物を建物単位で確認できる一覧ページです。遠賀川源流域の自然環境に包まれた住宅エリアの建物情報を、住所や募集状況を建物単位で比較しながら探せます。"},
)


def _format_yen(value: object) -> str:
    if value is None:
        return "—"
    try:
        return f"{int(float(str(value).strip().replace(',', ''))):,}"
    except (TypeError, ValueError):
        return "—"


def _format_built_label(building: dict) -> str | None:
    built = str(building.get("building_built_year_month") or "").strip()
    age = building.get("derived_built_age_years")
    if built:
        match = re.match(r"^\s*(\d{4})[-/](\d{1,2})\s*$", built)
        if match:
            ym = f"{int(match.group(1))}年{int(match.group(2))}月"
            if isinstance(age, int):
                if age <= 0:
                    return "新築"
                if age <= 3:
                    return "築浅"
                return f"{ym}［築{age}年］"
            return ym
    if isinstance(age, int):
        if age <= 0:
            return "新築"
        if age <= 3:
            return "築浅"
        return f"築{age}年"
    return None


def _format_range(min_value: object, max_value: object, *, suffix: str = "") -> str | None:
    if min_value is None and max_value is None:
        return None
    if min_value is None:
        min_value = max_value
    if max_value is None:
        max_value = min_value
    if min_value == max_value:
        if suffix == "円":
            return f"{_format_yen(min_value)}{suffix}"
        if suffix == "万円":
            return f"{_format_man_value(min_value)}{suffix}"
        return f"{min_value}{suffix}"
    if suffix == "円":
        return f"{_format_yen(min_value)}{suffix}〜{_format_yen(max_value)}{suffix}"
    if suffix == "万円":
        return f"{_format_man_value(min_value)}{suffix}〜{_format_man_value(max_value)}{suffix}"
    return f"{min_value}{suffix}〜{max_value}{suffix}"


def _format_man_value(value: object) -> str:
    try:
        num = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return str(value)
    if num.is_integer():
        return f"{int(num):,}"
    text = f"{num:,.2f}".rstrip("0").rstrip(".")
    return text


def _normalize_structure_label(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = unicodedata.normalize("NFKC", text)
    ascii_text = normalized.upper()
    if ascii_text in {"RC", "RC造"}:
        return "RC"
    if ascii_text in {"SRC", "SRC造"}:
        return "SRC"
    if normalized in {"軽量鉄骨", "軽量鉄骨造"}:
        return "軽量鉄骨"
    if normalized in {"鉄骨", "鉄骨造"}:
        return "鉄骨"
    if normalized in {"木", "木造"}:
        return "木造"
    return text


def _normalize_access_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.replace("　", " ")).strip()


def _is_numeric_only_access(value: str) -> bool:
    text = _normalize_access_text(value)
    if not text:
        return True
    return bool(ACCESS_NUMERIC_ONLY_RE.fullmatch(text))


def _format_access_info_for_display(value: object) -> str | None:
    raw = _normalize_access_text(value)
    if not raw:
        return None

    candidates: list[str] = []
    for match in re.finditer(r"([^\s　、,()/（）]+駅)([^、,\n]*)", raw):
        station = _normalize_access_text(match.group(1))
        tail = _normalize_access_text(match.group(2))
        behavior = re.search(r"(徒歩|バス|下車|車)", tail)
        if behavior:
            tail = tail[behavior.start():].strip()
        candidate = _normalize_access_text(f"{station} {tail}".strip())
        if not candidate or _is_numeric_only_access(candidate):
            continue
        candidates.append(candidate)

    if candidates:
        return " / ".join(dict.fromkeys(candidates))
    if _is_numeric_only_access(raw):
        return None
    return raw


def _format_layout_label(layout_types: list[str]) -> str | None:
    labels = []
    for item in layout_types:
        text = str(item or "").strip()
        if text and text not in labels:
            labels.append(text)
    if not labels:
        return None
    if len(labels) == 1:
        return labels[0]
    if len(labels) <= 3:
        return "、".join(labels)
    return f"{labels[0]}〜{labels[-1]}"


def _format_text_label(values: list[object]) -> str | None:
    labels: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in {"-", "--", "- -", "なし"}:
            continue
        if text not in labels:
            labels.append(text)
    if not labels:
        return None
    if len(labels) == 1:
        return labels[0]
    if len(labels) <= 3:
        return "、".join(labels)
    return f"{labels[0]}〜{labels[-1]}"


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


def _to_ascii_digits(value: str) -> str:
    return value.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


def _kanji_chome_to_ascii(rest: str) -> str:
    kanji_map = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}
    return re.sub(r"([一二三四五六七八九])丁目", lambda m: f"{kanji_map[m.group(1)]}丁目", rest)


def _build_display_address(address_full: object) -> str:
    text = str(address_full or "").strip()
    if not text:
        return ""
    text = _to_ascii_digits(text).replace("　", "")
    text = re.sub(r"^福岡県", "", text)
    city_match = re.match(r"^((?:[^市]+市)?(?:[^区]+区|[^町]+町|[^村]+村)?)(.*)$", text)
    if not city_match:
        return text
    prefix = city_match.group(1)
    rest = city_match.group(2).strip()
    if not rest:
        return prefix

    rest = _kanji_chome_to_ascii(rest)
    chome_match = re.search(r"(.+?)(\d+)丁目", rest)
    if chome_match:
        return f"{prefix}{chome_match.group(1)}{chome_match.group(2)}丁目"

    hyphen_chome_match = re.search(r"(.+?)(\d+)-\d+(?:-\d+)?", rest)
    if hyphen_chome_match:
        return f"{prefix}{hyphen_chome_match.group(1)}{hyphen_chome_match.group(2)}丁目"

    town_match = re.search(r"(.+?)(?:\d+番地|\d+番|\d+-\d+|[0-9].*)", rest)
    if town_match:
        return f"{prefix}{town_match.group(1)}".rstrip()
    return f"{prefix}{rest}".rstrip()


def _resolve_address_mode(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"full", "short"}:
        return normalized
    return DEFAULT_ADDRESS_MODE


def _resolve_theme(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"default", "ph", "mercari"}:
        return normalized
    return DEFAULT_THEME


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


def _to_float_or_zero(value: object) -> float:
    if value is None:
        return 0.0
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _has_meaningful_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _build_area_base_score(building: dict) -> float:
    vacancy_count = max(0.0, _to_float_or_zero(building.get("vacancy_count")))
    sale_listing_count = max(0.0, _to_float_or_zero(building.get("sale_listing_count")))
    active_listing_count = sale_listing_count if (building.get("property_kind") == "bunjo" and sale_listing_count > 0) else vacancy_count
    listing_bonus = min(active_listing_count, 5.0) * 12.0

    info_bonus = 0.0
    for key in (
        "rent_yen_min",
        "rent_yen_max",
        "area_sqm_min",
        "area_sqm_max",
        "structure",
        "building_structure",
        "building_built_year_month",
    ):
        if _has_meaningful_value(building.get(key)):
            info_bonus += 3.0
    if _has_meaningful_value(building.get("property_kind")):
        info_bonus += 2.0

    updated_epoch = int(_to_float_or_zero(building.get("updated_epoch")))
    if updated_epoch > 0:
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        age_days = max(0, (now_epoch - updated_epoch) // 86400)
        recency_bonus = max(0.0, 40.0 - min(float(age_days), 40.0))
    else:
        recency_bonus = 0.0

    return listing_bonus + info_bonus + recency_bonus


def _build_area_sort_score(building: dict) -> float:
    base_score = _build_area_base_score(building)
    popularity_score = _to_float_or_zero(building.get("popularity_score"))
    return base_score + popularity_score


def _sort_area_buildings(buildings: list[dict]) -> list[dict]:
    return sorted(
        buildings,
        key=lambda building: (
            -_build_area_sort_score(building),
            -int(_to_float_or_zero(building.get("updated_epoch"))),
            str(building.get("building_key") or ""),
        ),
    )


def _format_range(min_value: object, max_value: object, suffix: str) -> str | None:
    if min_value is None and max_value is None:
        return None

    def _label(value: object) -> str:
        if suffix == "円":
            return _format_yen(value)
        if suffix == "万円":
            return _format_man_value(value)
        return str(value)

    if min_value is not None and max_value is not None:
        if min_value == max_value:
            return f"{_label(min_value)}{suffix}"
        return f"{_label(min_value)}{suffix}〜{_label(max_value)}{suffix}"
    if min_value is not None:
        return f"{_label(min_value)}{suffix}〜"
    return f"〜{_label(max_value)}{suffix}"


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

    structure = _normalize_structure_label(building.get("building_structure") or building.get("structure"))
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


def _build_breadcrumb_json_ld(items: list[dict[str, str]]) -> str:
    payload = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": index,
                "name": item["name"],
                "item": item["url"],
            }
            for index, item in enumerate(items, start=1)
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


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
            COALESCE(NULLIF(s.structure, ''), b.structure) AS structure,
            s.building_built_year_month,
            s.building_built_age_years,
            COALESCE(NULLIF(s.building_structure, ''), NULLIF(s.structure, ''), b.structure) AS building_structure,
            s.building_availability_label,
            COALESCE(s.has_rental, 0) AS has_rental,
            COALESCE(s.has_sale, 0) AS has_sale,
            COALESCE(s.vacancy_count, 0) AS vacancy_count,
            s.sale_listing_count,
            s.last_updated,
            b.access_info,
            b.floor_count_text,
            b.total_units,
            b.management_style,
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
            b.structure AS structure,
            NULL AS building_built_year_month,
            NULL AS building_built_age_years,
            b.structure AS building_structure,
            NULL AS building_availability_label,
            0 AS has_rental,
            0 AS has_sale,
            0 AS vacancy_count,
            NULL AS sale_listing_count,
            NULL AS last_updated,
            b.access_info,
            b.floor_count_text,
            b.total_units,
            b.management_style,
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
    sponsor_rows = conn.execute(
        """
        SELECT building_key, company_name, catch_copy, coverage_domains, coverage_areas, cta_label, cta_url
        FROM building_page_sponsors
        WHERE COALESCE(is_active, 1) = 1
        """
    ).fetchall()
    sponsor_map = {str(row["building_key"]): dict(row) for row in sponsor_rows}
    rental_summary_rows = conn.execute(
        "SELECT * FROM building_rental_summaries"
    ).fetchall()
    rental_summary_map = {str(row["building_key"]): dict(row) for row in rental_summary_rows}
    sale_summary_rows = conn.execute(
        "SELECT * FROM building_sale_summaries"
    ).fetchall()
    sale_summary_map = {str(row["building_key"]): dict(row) for row in sale_summary_rows}
    alias_rows = conn.execute("SELECT alias_key, canonical_key FROM building_key_aliases").fetchall()
    alias_map = {str(row["alias_key"]): str(row["canonical_key"]) for row in alias_rows}
    rental_terms_rows = conn.execute(
        """
        SELECT building_key, rent_yen, maint_yen, area_sqm, layout, deposit_text, key_money_text, floor_text
        FROM listings
        WHERE (
            ingest_run_id IN (SELECT ingest_run_id FROM current_ingest_snapshots)
            OR (
                ingest_run_id IS NULL
                AND NOT EXISTS (SELECT 1 FROM current_ingest_snapshots)
            )
        )
        """
    ).fetchall()
    rental_terms_map: dict[str, dict[str, list[object]]] = {}
    rental_current_map: dict[str, dict[str, object]] = {}
    sale_current_map: dict[str, dict[str, object]] = {}
    for row in rental_terms_rows:
        building_key = str(row["building_key"] or "").strip()
        if not building_key:
            continue
        canonical_key = alias_map.get(building_key, building_key)
        bucket = rental_terms_map.setdefault(canonical_key, {"deposit": [], "key_money": []})
        bucket["deposit"].append(row["deposit_text"])
        bucket["key_money"].append(row["key_money_text"])
        current = rental_current_map.setdefault(
            canonical_key,
            {"rents": [], "maints": [], "areas": [], "layouts": [], "floors": []},
        )
        if row["rent_yen"] is not None:
            current["rents"].append(row["rent_yen"])
        if row["maint_yen"] is not None:
            current["maints"].append(row["maint_yen"])
        if row["area_sqm"] is not None:
            current["areas"].append(row["area_sqm"])
        layout = str(row["layout"] or "").strip()
        if layout and layout not in current["layouts"]:
            current["layouts"].append(layout)
        floor_text = str(row["floor_text"] or "").strip()
        if floor_text and floor_text not in current["floors"]:
            current["floors"].append(floor_text)
    sale_rows = conn.execute(
        """
        SELECT building_key, price_yen, area_sqm, layout, floor_text, direction_text, tsubo_unit_price_yen
        FROM sale_listings
        WHERE (
            ingest_run_id IN (SELECT ingest_run_id FROM current_ingest_snapshots)
            OR (
                ingest_run_id IS NULL
                AND NOT EXISTS (SELECT 1 FROM current_ingest_snapshots)
            )
        )
        ORDER BY id DESC
        """
    ).fetchall()
    for row in sale_rows:
        building_key = str(row["building_key"] or "").strip()
        if not building_key:
            continue
        canonical_key = alias_map.get(building_key, building_key)
        current = sale_current_map.setdefault(
            canonical_key,
            {
                "price_yen": None,
                "area_sqm": None,
                "layout": None,
                "floor_text": None,
                "direction_text": None,
                "tsubo_unit_price_yen": None,
            },
        )
        if current["price_yen"] is None and row["price_yen"] is not None:
            current["price_yen"] = row["price_yen"]
        if current["area_sqm"] is None and row["area_sqm"] is not None:
            current["area_sqm"] = row["area_sqm"]
        layout = str(row["layout"] or "").strip()
        if current["layout"] is None and layout:
            current["layout"] = layout
        floor_text = str(row["floor_text"] or "").strip()
        if current["floor_text"] is None and floor_text:
            current["floor_text"] = floor_text
        direction_text = str(row["direction_text"] or "").strip()
        if current["direction_text"] is None and direction_text:
            current["direction_text"] = direction_text
        if current["tsubo_unit_price_yen"] is None and row["tsubo_unit_price_yen"] is not None:
            current["tsubo_unit_price_yen"] = row["tsubo_unit_price_yen"]
    merged_rental_summary_map: dict[str, dict] = {}
    for key, row in rental_summary_map.items():
        canonical_key = alias_map.get(key, key)
        current = merged_rental_summary_map.get(canonical_key)
        if current is None:
            merged_rental_summary_map[canonical_key] = dict(row)
            continue
        current_updated = str(current.get("updated_at") or "")
        row_updated = str(row.get("updated_at") or "")
        current_count = int(current.get("vacancy_count") or 0)
        row_count = int(row.get("vacancy_count") or 0)
        if (row_count, row_updated) > (current_count, current_updated):
            merged_rental_summary_map[canonical_key] = dict(row)
    rental_summary_map = merged_rental_summary_map

    merged_sale_summary_map: dict[str, dict] = {}
    for key, row in sale_summary_map.items():
        canonical_key = alias_map.get(key, key)
        current = merged_sale_summary_map.get(canonical_key)
        if current is None:
            merged_sale_summary_map[canonical_key] = dict(row)
            continue
        current_updated = str(current.get("updated_at") or "")
        row_updated = str(row.get("updated_at") or "")
        current_count = int(current.get("sale_listing_count") or 0)
        row_count = int(row.get("sale_listing_count") or 0)
        if (row_count, row_updated) > (current_count, current_updated):
            merged_sale_summary_map[canonical_key] = dict(row)
    sale_summary_map = merged_sale_summary_map
    conn.close()
    for building in building_list:
        building["sponsor"] = sponsor_map.get(str(building.get("building_key")))
        building["rental_summary"] = rental_summary_map.get(str(building.get("building_key")))
        building["sale_summary"] = sale_summary_map.get(str(building.get("building_key")))
        rental_terms = rental_terms_map.get(str(building.get("building_key")), {"deposit": [], "key_money": []})
        building["rental_deposit_label"] = _format_text_label(rental_terms.get("deposit", []))
        building["rental_key_money_label"] = _format_text_label(rental_terms.get("key_money", []))
        building["rental_current"] = rental_current_map.get(str(building.get("building_key")), {})
        building["sale_current"] = sale_current_map.get(str(building.get("building_key")), {})
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
                "address": b.get("render_address") or b.get("address"),
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
                "listing_mode": b.get("listing_mode") or "rental",
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
                "address": b.get("render_address") or b.get("address"),
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
                "listing_mode": b.get("listing_mode") or "rental",
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
    address_mode: str,
    default_theme: str,
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
    selected_mode = _resolve_address_mode(address_mode)
    for b in buildings:
        b["detail_filename"] = _build_detail_filename(b)
        b["legacy_detail_filename"] = f"{b['building_key']}.html"
        b["address_full"] = b.get("address")
        b["display_address"] = _build_display_address(b.get("address"))
        b["render_address"] = b.get("display_address") if selected_mode == "short" else b.get("address_full")
        has_sale = bool(b.get("has_sale")) or bool((b.get("sale_listing_count") or 0) > 0)
        has_rental = bool(b.get("has_rental")) or bool((b.get("vacancy_count") or 0) > 0)
        if has_sale and has_rental:
            listing_mode = "both"
        elif has_sale:
            listing_mode = "sale"
        else:
            listing_mode = "rental"
        b["has_sale_final"] = has_sale
        b["has_rental_final"] = has_rental
        b["listing_mode"] = listing_mode
    total_vacant = sum((b.get("vacancy_count") or 0) for b in buildings)
    parsed_dates = [parsed for parsed in (_build_summary_date(b) for b in buildings) if parsed is not None]
    latest_data_date = max(parsed_dates, default=None)
    latest_data_date_label = latest_data_date.strftime("%Y/%m/%d") if latest_data_date else "—"
    area_buildings_map = {spec["path"]: [] for spec in AREA_PAGE_SPECS}
    for building in buildings:
        matched_area = _resolve_area_spec(building.get("address"))
        if matched_area:
            area_buildings_map[matched_area["path"]].append(building)
    for area_path, area_buildings in area_buildings_map.items():
        area_buildings_map[area_path] = _sort_area_buildings(area_buildings)
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
            default_theme=default_theme,
        ),
        encoding="utf-8",
    )

    for area_spec in AREA_PAGE_SPECS:
        area_dir = output_dir / area_spec["path"].strip("/")
        area_dir.mkdir(parents=True, exist_ok=True)
        area_name = area_spec["label"]
        area_canonical_url = _build_canonical_url(site_origin, base_path, area_spec["path"])
        area_breadcrumb_items = [
            {"name": "ホーム", "url": _build_canonical_url(site_origin, base_path, "/")},
            {"name": area_name, "url": area_canonical_url},
        ]
        area_dir.joinpath("index.html").write_text(
            area_tpl.render(
                area_name=area_name,
                intro_text=area_spec["intro_text"],
                buildings=area_buildings_map[area_spec["path"]],
                page_title=f"{area_name}の建物一覧・住所・募集情報 | 建物マップ",
                page_description=area_spec["intro_text"],
                canonical_url=area_canonical_url,
                breadcrumb_items=area_breadcrumb_items,
                breadcrumb_json_ld=_build_breadcrumb_json_ld(area_breadcrumb_items),
                line_cta_url=line_cta_url,
                line_deep_link_url=line_deep_link_url,
                base_path=base_path,
                google_site_verification=google_site_verification,
                default_theme=default_theme,
            ),
            encoding="utf-8",
        )

    for b in buildings:
        maps_url = _build_google_maps_url(b.get("address"))
        maps_embed_url = _build_google_maps_embed_url(b.get("address"), google_maps_embed_api_key)
        rental_summary = b.get("rental_summary") or {}
        sale_summary = b.get("sale_summary") or {}
        b["detail_mode"] = b.get("listing_mode") or "rental"
        b["built_label"] = _format_built_label(b)
        b["rental_vacancy_label"] = (
            f"{int(b.get('vacancy_count') or 0)}件" if (b.get("vacancy_count") or 0) > 0 else "現在、募集中はありません。"
        )
        rental_current = b.get("rental_current") or {}
        current_rents = rental_current.get("rents") or []
        rent_min = min(current_rents) if current_rents else (rental_summary.get("rent_yen_min") if rental_summary else b.get("rent_yen_min"))
        rent_max = max(current_rents) if current_rents else (rental_summary.get("rent_yen_max") if rental_summary else b.get("rent_yen_max"))
        b["rental_rent_label"] = _format_range(
            _format_yen(rent_min) if rent_min is not None else None,
            _format_yen(rent_max) if rent_max is not None else None,
            suffix="円",
        )
        current_maints = rental_current.get("maints") or []
        maint_min = min(current_maints) if current_maints else (rental_summary.get("maint_yen_min") if rental_summary else None)
        maint_max = max(current_maints) if current_maints else (rental_summary.get("maint_yen_max") if rental_summary else None)
        b["rental_maint_label"] = _format_range(
            maint_min,
            maint_max,
            suffix="円",
        )
        current_layouts = rental_current.get("layouts") or []
        b["rental_layout_label"] = _format_layout_label(
            current_layouts or (json.loads(rental_summary.get("layout_types_json") or "[]") if rental_summary else b.get("layout_types") or [])
        )
        current_areas = rental_current.get("areas") or []
        area_min = min(current_areas) if current_areas else (rental_summary.get("area_sqm_min") if rental_summary else b.get("area_sqm_min"))
        area_max = max(current_areas) if current_areas else (rental_summary.get("area_sqm_max") if rental_summary else b.get("area_sqm_max"))
        b["rental_area_label"] = _format_range(
            area_min,
            area_max,
            suffix="㎡",
        )
        b["rental_floor_label"] = _format_text_label(rental_current.get("floors", []))
        b["rental_move_in_label"] = rental_summary.get("move_in_summary") if rental_summary else b.get("building_availability_label")
        b["access_info"] = _format_access_info_for_display(b.get("access_info"))
        b["display_structure"] = _normalize_structure_label(b.get("building_structure") or b.get("structure"))
        sale_count = sale_summary.get("sale_listing_count") if sale_summary else b.get("sale_listing_count")
        sale_current = b.get("sale_current") or {}
        b["sale_status_label"] = f"{int(sale_count)}件" if (sale_count or 0) > 0 else "現在、販売中の住戸はありません。"
        sale_price_current = sale_current.get("price_yen")
        b["sale_price_label"] = _format_range(
            (sale_price_current / 10000) if sale_price_current is not None else ((sale_summary.get("price_yen_min") if sale_summary else b.get("sale_price_yen_min")) / 10000 if (sale_summary.get("price_yen_min") if sale_summary else b.get("sale_price_yen_min")) else None),
            (sale_price_current / 10000) if sale_price_current is not None else ((sale_summary.get("price_yen_max") if sale_summary else b.get("sale_price_yen_max")) / 10000 if (sale_summary.get("price_yen_max") if sale_summary else b.get("sale_price_yen_max")) else None),
            suffix="万円",
        )
        sale_area_current = sale_current.get("area_sqm")
        b["sale_area_label"] = _format_range(
            sale_area_current if sale_area_current is not None else (sale_summary.get("area_sqm_min") if sale_summary else b.get("sale_area_sqm_min")),
            sale_area_current if sale_area_current is not None else (sale_summary.get("area_sqm_max") if sale_summary else b.get("sale_area_sqm_max")),
            suffix="㎡",
        )
        sale_layout_current = sale_current.get("layout")
        b["sale_layout_label"] = (
            _format_layout_label([sale_layout_current])
            if sale_layout_current
            else (_format_layout_label(json.loads(sale_summary.get("layout_types_json") or "[]")) if sale_summary else _format_layout_label(json.loads(b.get("sale_layout_types_json") or "[]")))
        )
        sqm_unit_current = sale_current.get("tsubo_unit_price_yen")
        b["sale_sqm_price_label"] = _format_range(
            (sqm_unit_current / 10000) if sqm_unit_current is not None else ((sale_summary.get("tsubo_unit_price_yen_min") / 10000) if sale_summary and sale_summary.get("tsubo_unit_price_yen_min") else None),
            (sqm_unit_current / 10000) if sqm_unit_current is not None else ((sale_summary.get("tsubo_unit_price_yen_max") / 10000) if sale_summary and sale_summary.get("tsubo_unit_price_yen_max") else None),
            suffix="万円/m²",
        )
        b["sale_floor_label"] = sale_current.get("floor_text") or (sale_summary.get("floor_summary") if sale_summary else None)
        b["sale_direction_label"] = sale_current.get("direction_text") or (sale_summary.get("direction_summary") if sale_summary else None)
        seo = _build_building_seo(b, site_origin=site_origin, base_path=base_path)
        detail_path = f"{base_path}/b/{b['detail_filename']}"
        area_hub = None
        area_spec = _resolve_area_spec(b.get("address"))
        if area_spec:
            area_hub = {
                "name": area_spec["label"],
                "url": f"{base_path}{area_spec['path']}",
            }
        detail_canonical_url = seo["canonical_url"]
        breadcrumb_items = [
            {"name": "ホーム", "url": _build_canonical_url(site_origin, base_path, "/")},
        ]
        if area_spec:
            breadcrumb_items.append(
                {"name": area_spec["label"], "url": _build_canonical_url(site_origin, base_path, area_spec["path"])}
            )
        breadcrumb_items.append({"name": str(b.get("name") or "建物詳細"), "url": detail_canonical_url})
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
            canonical_url=detail_canonical_url,
            breadcrumb_items=breadcrumb_items,
            breadcrumb_json_ld=_build_breadcrumb_json_ld(breadcrumb_items),
            base_path=base_path,
            google_site_verification=google_site_verification,
            default_theme=default_theme,
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
    address_mode = _resolve_address_mode(os.getenv("TATEMONO_MAP_ADDRESS_MODE", DEFAULT_ADDRESS_MODE))
    default_theme = _resolve_theme(os.getenv("TATEMONO_MAP_THEME", DEFAULT_THEME))
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
        address_mode=address_mode,
        default_theme=default_theme,
    )


def build_dist_versions(db_path: str, output_dir: str, *, base_path: str = DEFAULT_BASE_PATH) -> None:
    load_dotenv()
    line_cta_url = os.getenv("TATEMONO_MAP_LINE_CTA_URL", DEFAULT_LINE_UNIVERSAL_URL).strip() or DEFAULT_LINE_UNIVERSAL_URL
    line_deep_link_url = os.getenv("TATEMONO_MAP_LINE_DEEP_LINK_URL", DEFAULT_LINE_DEEP_LINK).strip() or DEFAULT_LINE_DEEP_LINK
    google_maps_embed_api_key = os.getenv("TATEMONO_MAP_GOOGLE_MAPS_EMBED_API_KEY", "")
    google_site_verification = os.getenv("TATEMONO_MAP_GOOGLE_SITE_VERIFICATION", DEFAULT_GOOGLE_SITE_VERIFICATION).strip()
    site_origin = _resolve_site_origin()
    address_mode = _resolve_address_mode(os.getenv("TATEMONO_MAP_ADDRESS_MODE", DEFAULT_ADDRESS_MODE))
    default_theme = _resolve_theme(os.getenv("TATEMONO_MAP_THEME", DEFAULT_THEME))
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
        address_mode=address_mode,
        default_theme=default_theme,
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
        address_mode=address_mode,
        default_theme=default_theme,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="data/tatemono_map.sqlite3")
    parser.add_argument("--output-dir", default="dist")
    parser.add_argument("--version", choices=("v1", "v2", "all"), default="all")
    parser.add_argument("--base-path", default=os.getenv("TATEMONO_MAP_BASE_PATH", DEFAULT_BASE_PATH))
    parser.add_argument("--address-mode", choices=("full", "short"), default=os.getenv("TATEMONO_MAP_ADDRESS_MODE", DEFAULT_ADDRESS_MODE))
    parser.add_argument("--theme", choices=("default", "ph", "mercari"), default=os.getenv("TATEMONO_MAP_THEME", DEFAULT_THEME))
    args = parser.parse_args()
    os.environ["TATEMONO_MAP_ADDRESS_MODE"] = args.address_mode
    os.environ["TATEMONO_MAP_THEME"] = args.theme

    if args.version == "all":
        build_dist_versions(args.db_path, args.output_dir, base_path=args.base_path)
    elif args.version == "v2":
        build_dist(args.db_path, args.output_dir, template_root="templates_v2", base_path=args.base_path)
    else:
        build_dist(args.db_path, args.output_dir, template_root="templates", base_path=args.base_path)
    print("dist generated")


if __name__ == "__main__":
    main()
