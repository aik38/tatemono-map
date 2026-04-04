from scripts.mansion_review_list_to_master_import import _sanitize_mansion_review_layout


def test_sanitize_layout_accepts_valid_patterns() -> None:
    assert _sanitize_mansion_review_layout("ワンルーム") == "ワンルーム"
    assert _sanitize_mansion_review_layout("1LDK") == "1LDK"
    assert _sanitize_mansion_review_layout("2SLDK") == "2SLDK"
    assert _sanitize_mansion_review_layout("3LDK+S") == "3LDK+S"


def test_sanitize_layout_rejects_polluted_text() -> None:
    bad = "住所・交通・築年数・総戸数・賃料表・号室・全 件を表示する・function()"
    assert _sanitize_mansion_review_layout(bad) == ""
    assert _sanitize_mansion_review_layout("<script>alert(1)</script>") == ""
    assert _sanitize_mansion_review_layout("2LDK 号室") == ""
