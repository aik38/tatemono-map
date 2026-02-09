from tatemono_map.ingest.ulucks_playwright import is_valid_smartlink_html


def test_error_html_is_rejected() -> None:
    ok, reason = is_valid_smartlink_html("<html><body>ログインしてください</body></html>")
    assert not ok
    assert reason == "error_screen"
