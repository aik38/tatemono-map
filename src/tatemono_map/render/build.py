from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape

from tatemono_map.db.repo import connect

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


def _load_buildings(db_path: str) -> tuple[list[dict], int, int, int, int]:
    conn = connect(db_path)
    canonical_buildings_count = conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
    summary_buildings_count = conn.execute("SELECT COUNT(DISTINCT building_key) FROM building_summaries").fetchone()[0]
    buildings_count = summary_buildings_count if canonical_buildings_count == 0 else canonical_buildings_count
    vacancy_total = conn.execute("SELECT COALESCE(SUM(vacancy_count), 0) FROM building_summaries").fetchone()[0]
    buildings = conn.execute(
        """
        SELECT
            building_key, name, raw_name, address,
            rent_yen_min, rent_yen_max, area_sqm_min, area_sqm_max,
            layout_types_json, move_in_dates_json, vacancy_count, last_updated, updated_at
        FROM building_summaries
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
        building_list.append(_sanitize_building(building))
    conn.close()
    return building_list, canonical_buildings_count, summary_buildings_count, buildings_count, vacancy_total


def _build_dist_version(
    output_dir: Path,
    buildings: list[dict],
    *,
    canonical_buildings_count: int,
    summary_buildings_count: int,
    buildings_count: int,
    vacancy_total: int,
    template_root: str,
    line_cta_url: str,
    line_deep_link_url: str,
) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    (output_dir / "b").mkdir(parents=True, exist_ok=True)

    env = Environment(loader=FileSystemLoader(template_root), autoescape=select_autoescape(["html"]))
    env.filters["yen"] = _format_yen
    index_tpl = env.get_template("index.html.j2")
    building_tpl = env.get_template("building.html.j2")

    total_buildings = len(buildings)
    total_vacant = sum((b.get("vacancy_count") or 0) for b in buildings)
    parsed_dates = [parsed for parsed in (_build_summary_date(b) for b in buildings) if parsed is not None]
    latest_data_date = max(parsed_dates, default=None)
    latest_data_date_label = latest_data_date.strftime("%Y/%m/%d") if latest_data_date else "—"

    (output_dir / "index.html").write_text(
        index_tpl.render(
            buildings=buildings,
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
        ),
        encoding="utf-8",
    )

    for b in buildings:
        maps_url = None
        address = (b.get("address") or "").strip()
        if address:
            maps_url = f"https://maps.google.com/?q={quote_plus(address)}"
        html = building_tpl.render(
            building=b,
            maps_url=maps_url,
            line_cta_url=line_cta_url,
            line_deep_link_url=line_deep_link_url,
        )
        (output_dir / "b" / f"{b['building_key']}.html").write_text(html, encoding="utf-8")

    (output_dir / ".nojekyll").touch()
    _validate_public_dist(output_dir)


def build_dist(db_path: str, output_dir: str, *, template_root: str = "templates") -> None:
    load_dotenv()
    line_cta_url = os.getenv("TATEMONO_MAP_LINE_CTA_URL", DEFAULT_LINE_UNIVERSAL_URL).strip() or DEFAULT_LINE_UNIVERSAL_URL
    line_deep_link_url = os.getenv("TATEMONO_MAP_LINE_DEEP_LINK_URL", DEFAULT_LINE_DEEP_LINK).strip() or DEFAULT_LINE_DEEP_LINK

    buildings, canonical_buildings_count, summary_buildings_count, buildings_count, vacancy_total = _load_buildings(db_path)
    _build_dist_version(
        Path(output_dir),
        buildings,
        canonical_buildings_count=canonical_buildings_count,
        summary_buildings_count=summary_buildings_count,
        buildings_count=buildings_count,
        vacancy_total=vacancy_total,
        template_root=template_root,
        line_cta_url=line_cta_url,
        line_deep_link_url=line_deep_link_url,
    )


def build_dist_versions(db_path: str, output_dir: str) -> None:
    load_dotenv()
    line_cta_url = os.getenv("TATEMONO_MAP_LINE_CTA_URL", DEFAULT_LINE_UNIVERSAL_URL).strip() or DEFAULT_LINE_UNIVERSAL_URL
    line_deep_link_url = os.getenv("TATEMONO_MAP_LINE_DEEP_LINK_URL", DEFAULT_LINE_DEEP_LINK).strip() or DEFAULT_LINE_DEEP_LINK

    out = Path(output_dir)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    buildings, canonical_buildings_count, summary_buildings_count, buildings_count, vacancy_total = _load_buildings(db_path)
    _build_dist_version(
        out,
        buildings,
        canonical_buildings_count=canonical_buildings_count,
        summary_buildings_count=summary_buildings_count,
        buildings_count=buildings_count,
        vacancy_total=vacancy_total,
        template_root="templates_v2",
        line_cta_url=line_cta_url,
        line_deep_link_url=line_deep_link_url,
    )
    _build_dist_version(
        out / "v1",
        buildings,
        canonical_buildings_count=canonical_buildings_count,
        summary_buildings_count=summary_buildings_count,
        buildings_count=buildings_count,
        vacancy_total=vacancy_total,
        template_root="templates",
        line_cta_url=line_cta_url,
        line_deep_link_url=line_deep_link_url,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="data/tatemono_map.sqlite3")
    parser.add_argument("--output-dir", default="dist")
    parser.add_argument("--version", choices=("v1", "v2", "all"), default="all")
    args = parser.parse_args()

    if args.version == "all":
        build_dist_versions(args.db_path, args.output_dir)
    elif args.version == "v2":
        build_dist(args.db_path, args.output_dir, template_root="templates_v2")
    else:
        build_dist(args.db_path, args.output_dir, template_root="templates")
    print("dist generated")


if __name__ == "__main__":
    main()
