from __future__ import annotations

import argparse
import json
import os
import re
import shutil
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


def _load_buildings(db_path: str) -> list[dict]:
    conn = connect(db_path)
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
        building_list.append(_sanitize_building(building))
    conn.close()
    return building_list


def _build_dist_version(
    output_dir: Path,
    buildings: list[dict],
    *,
    template_root: str,
    line_cta_url: str,
    line_deep_link_url: str,
) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    (output_dir / "b").mkdir(parents=True, exist_ok=True)

    env = Environment(loader=FileSystemLoader(template_root), autoescape=select_autoescape(["html"]))
    index_tpl = env.get_template("index.html.j2")
    building_tpl = env.get_template("building.html.j2")

    (output_dir / "index.html").write_text(index_tpl.render(buildings=buildings), encoding="utf-8")

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

    buildings = _load_buildings(db_path)
    _build_dist_version(
        Path(output_dir),
        buildings,
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

    buildings = _load_buildings(db_path)
    _build_dist_version(
        out / "v1",
        buildings,
        template_root="templates",
        line_cta_url=line_cta_url,
        line_deep_link_url=line_deep_link_url,
    )
    _build_dist_version(
        out / "v2",
        buildings,
        template_root="templates_v2",
        line_cta_url=line_cta_url,
        line_deep_link_url=line_deep_link_url,
    )

    (out / "index.html").write_text(
        """<!doctype html><html lang=\"ja\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>tatemono-map</title></head><body><ul><li><a href=\"./v1/index.html\">v1</a></li><li><a href=\"./v2/index.html\">v2</a></li></ul></body></html>""",
        encoding="utf-8",
    )
    (out / ".nojekyll").touch()


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
