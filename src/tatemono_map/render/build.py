from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import quote_plus

from jinja2 import Environment, FileSystemLoader, select_autoescape

from tatemono_map.db.repo import connect
from tatemono_map.normalize.building_summaries import summarize_layout_counts


def build_dist(db_path: str, output_dir: str) -> None:
    conn = connect(db_path)
    out = Path(output_dir)
    (out / "b").mkdir(parents=True, exist_ok=True)

    env = Environment(loader=FileSystemLoader("templates"), autoescape=select_autoescape(["html"]))
    index_tpl = env.get_template("index.html.j2")
    building_tpl = env.get_template("building.html.j2")

    buildings = conn.execute("SELECT * FROM building_summaries ORDER BY updated_at DESC").fetchall()
    building_list = []
    for row in buildings:
        building = dict(row)
        building["layout_types"] = json.loads(building.get("layout_types_json") or "[]")
        building_list.append(building)

    (out / "index.html").write_text(index_tpl.render(buildings=building_list), encoding="utf-8")

    for b in building_list:
        layout_counts = summarize_layout_counts(conn, b["building_key"])
        maps_url = None
        address = (b.get("address") or "").strip()
        if address:
            maps_url = f"https://www.google.com/maps/search/?api=1&query={quote_plus(address)}"
        html = building_tpl.render(building=b, layout_counts=layout_counts, maps_url=maps_url)
        (out / "b" / f"{b['building_key']}.html").write_text(html, encoding="utf-8")

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
