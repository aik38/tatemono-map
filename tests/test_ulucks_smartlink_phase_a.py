from pathlib import Path

from tatemono_map.ingest import ulucks_smartlink_phase_a as phase_a


def test_phase_a_run_from_html_files_generates_building_summaries(tmp_path: Path):
    fixture_dir = Path(__file__).parent / "fixtures" / "ulucks"
    html_files = [
        fixture_dir / "smartlink_phase_a_page_1.html",
        fixture_dir / "smartlink_phase_a_page_2.html",
        fixture_dir / "smartlink_phase_a_page_3_empty.html",
    ]

    cards, summaries = phase_a.run_phase_a(
        url=None,
        html_files=html_files,
        max_pages=10,
        sleep_s=0,
        timeout_s=1,
        retry=0,
        cache_dir=None,
    )

    assert len(cards) == 3
    cp_tower_cards = [c for c in cards if c.building_name == "CPタワー"]
    assert len(cp_tower_cards) == 2

    out_csv = tmp_path / "building_summary.csv"
    phase_a._write_outputs(cards, summaries, out_json=None, out_csv=out_csv)  # noqa: SLF001
    content = out_csv.read_text(encoding="utf-8")
    assert "CPタワー" in content
    assert "53000" in content


def test_parse_card_ignores_search_form_noise():
    html = """
    <html><body>
      <div class='search'>賃料: 99万</div>
      <article>
        <a href='/view/smartview/abc999/'>ノイズマンション 101号室</a>
        <div>所在地: 福岡県福岡市南区1-1-1</div>
        <div>賃料: 5.5万</div>
        <div>間取り: 1K</div>
      </article>
    </body></html>
    """

    cards = phase_a.parse_smartlink_cards(html, source_page=1)
    assert len(cards) == 1
    assert cards[0].rent_yen == 55000


def test_safe_output_guard_rejects_sensitive_strings():
    try:
        phase_a._assert_safe_output("連絡先 TEL: 090-0000-0000")  # noqa: SLF001
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
