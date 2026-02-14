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


def build_dist(db_path: str, output_dir: str) -> None:
    load_dotenv()
    line_cta_url = os.getenv("TATEMONO_MAP_LINE_CTA_URL", "").strip()

    conn = connect(db_path)
    out = Path(output_dir)
    if out.exists():
        shutil.rmtree(out)
    (out / "b").mkdir(parents=True, exist_ok=True)

    env = Environment(loader=FileSystemLoader("templates"), autoescape=select_autoescape(["html"]))
    index_tpl = env.get_template("index.html.j2")
    building_tpl = env.get_template("building.html.j2")

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

    (out / "index.html").write_text(index_tpl.render(buildings=building_list), encoding="utf-8")

    for b in building_list:
        maps_url = None
        address = (b.get("address") or "").strip()
        if address:
            maps_url = f"https://maps.google.com/?q={quote_plus(address)}"
        html = building_tpl.render(building=b, maps_url=maps_url, line_cta_url=line_cta_url)
        (out / "b" / f"{b['building_key']}.html").write_text(html, encoding="utf-8")

    (out / ".nojekyll").touch()

    _validate_public_dist(out)
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="data/tatemono_map.sqlite3")
    parser.add_argument("--output-dir", default="dist")
    args = parser.parse_args()
    build_dist(args.db_path, args.output_dir)
    print("dist generated")


if __name__ == "__main__":
    main()
