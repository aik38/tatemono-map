from pathlib import Path

from tatemono_map.parse.ulucks_smartview import parse_smartview_html


def test_parse_smartview_patterns():
    base = Path("tests/fixtures/ulucks")
    for filename in ["smartview_table.html", "smartview_div.html", "smartview_fallback.html"]:
        parsed = parse_smartview_html((base / filename).read_text(encoding="utf-8"), fetched_at="2026-01-01T00:00:00+09:00")
        assert parsed.name
        assert parsed.address
        assert parsed.rent_yen is not None
        assert parsed.area_sqm is not None
        assert parsed.layout
