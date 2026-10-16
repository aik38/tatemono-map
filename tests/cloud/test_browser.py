"""Observed screens recreated with fictional data; no member HTML in GitHub."""
from __future__ import annotations

import os
import zipfile

import pytest
from playwright.sync_api import sync_playwright

from tatemono_map.cloud.collector import CollectionError, ORIGIN, collect_with_page, unpack_export, validate_config


@pytest.mark.parametrize("button_outside_form", [False, True])
@pytest.mark.parametrize("company_variant", ["second_cell", "third_cell", "no_link"])
@pytest.mark.parametrize("count,wrong_scope", [(1, False), (0, False), (1, True)])
def test_member_navigation_exclusive_checkbox_search_and_original_inline_pdf(config, pdf, tmp_path, count, wrong_scope, company_variant, button_outside_form):
    login = '<input type="text"><input type="password"><button onclick="location.href=\'/new\'">ログイン</button>'
    # Recreate the observed /company table: click the property's count link
    # in the unique row with the reviewed company name (not its literal href).
    count_cell = '<a href="/company/lists/8">1047</a>' if company_variant != "no_link" else '1047'
    prefix = '<td>他の列</td>' if company_variant == "third_cell" else ''
    company = ('<table><tbody><tr><td>株式会社不動産中央情報センター入居推進</td>'
               + prefix + '<td>' + count_cell + '</td></tr>'
               + '<tr><td>別の不動産会社</td><td><a href="/company/lists/9">200</a></td></tr></tbody></table>')
    search = '''<h2>物件検索（株式会社不動産中央情報センター）</h2>
<a href="/observed-print-action?actual=1" target="_blank">(新)エリア・物件別で印刷</a>
<form action="/company/lists/8" method="post">
<label><input type="checkbox" name="area" value="north" checked>小倉北区</label>
<label><input type="checkbox" name="area" value="south" OTHER>小倉南区</label>
<input type="text" name="building"><button type="submit">検　索</button></form>
<div>検索結果 COUNT 件中　1～60件を表示</div>'''.replace("COUNT", str(count))
    if button_outside_form:
        search = search.replace('<button type="submit">検　索</button>', '')
        search = search.replace('</form>',
            '''</form><button onclick="document.querySelector('form').requestSubmit()">検　索</button>''')
    requests = []
    with sync_playwright() as pw:
        launch = {"headless": True}
        if os.environ.get("TATEMONO_TEST_BROWSER"):
            launch["executable_path"] = os.environ["TATEMONO_TEST_BROWSER"]
        browser = pw.chromium.launch(**launch)
        context = browser.new_context(accept_downloads=True)
        # route.fetch is a real forwarder; use a local HTTP fixture backend for
        # print responses, while the browser retains the observed HTTPS origin.
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.end_headers()
                self.wfile.write(pdf.read_bytes())
            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def route(request):
            url = request.request.url
            path = url.split(".jp", 1)[1]
            requests.append((path, request.request.post_data))
            if path.startswith("/observed-print-action"):
                # The collector's handler captures after this route forwards
                # to the fixture. route.fallback changes the destination but
                # would fail origin checks; instead test capture via mocked
                # APIResponse from a real HTTP PDF response below.
                response = context.request.get(f"http://127.0.0.1:{server.server_port}/pdf")
                request.fulfill(response=response)
            else:
                if path == "/":
                    html = login
                elif path == "/new":
                    html = '<a href="/company">会社検索</a>'
                elif path == "/company":
                    html = company
                else:
                    posted = request.request.post_data or ""
                    if request.request.method == "POST":
                        assert "area=north" in posted and "area=south" not in posted
                    html = search.replace("OTHER", "checked" if request.request.method != "POST" or wrong_scope else "")
                request.fulfill(content_type="text/html; charset=utf-8", body=html)
        context.route(ORIGIN + "/**", route)
        page = context.new_page()
        # route.fetch is deliberately injected at the transport boundary only:
        # real browser navigation/clicks still select the actual print request.
        from playwright.sync_api import Route
        original_fetch = Route.fetch
        def fixture_fetch(self, **kwargs):
            if "/observed-print-action" in self.request.url:
                return context.request.get(f"http://127.0.0.1:{server.server_port}/pdf")
            return original_fetch(self, **kwargs)
        from unittest.mock import patch
        try:
            with patch.object(Route, "fetch", fixture_fetch):
                if wrong_scope:
                    with pytest.raises(CollectionError, match="not_exclusive"):
                        collect_with_page(page, config, {"username": "fake", "password": "fake"}, tmp_path / "downloads")
                else:
                    result = collect_with_page(page, config, {"username": "fake", "password": "fake"}, tmp_path / "downloads")
                    assert result.expected_rows == count
                    assert result.confirmed_zero == (count == 0)
                    assert result.evidence["company_navigation"] == (
                        "authenticated_direct_verified" if company_variant == "no_link"
                        else "observed_company_link")
                    import json
                    observation = json.loads((tmp_path / "ulucks-ui.private.json").read_text())
                    assert observation["verified_company_title"] is True
                    assert observation["search_controls"]["checkbox_count"] == 2
                    assert observation["search_controls"]["page_search_button_count"] == 1
                    assert observation["search_controls"]["search_button_count"] == (0 if button_outside_form else 1)
                    assert observation["search_completed"]["result_count"] == count
                    assert observation["expected_company_link_count"] == (0 if company_variant == "no_link" else 1)
                    assert "1047" not in str(observation)
                    if count:
                        assert result.pdfs[0].read_bytes() == pdf.read_bytes()
                        assert result.evidence["responses"][0]["path"] == "/observed-print-action"
                    else:
                        assert result.evidence["search_counts"] == [0, 0]
        finally:
            browser.close()
            server.shutdown()
            server.server_close()


def test_zip_does_not_extract_supplier_paths(pdf, tmp_path):
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../../private.pdf", pdf.read_bytes())
    assert unpack_export(archive, tmp_path) == [tmp_path / "ulucks-000.pdf"]
    assert not (tmp_path.parent / "private.pdf").exists()


@pytest.mark.parametrize("payload", [b"<html>login required</html>", b"%PDF-invalid"])
def test_error_html_and_invalid_pdf_rejected(payload, tmp_path):
    source = tmp_path / "export.bin"
    source.write_bytes(payload)
    with pytest.raises(CollectionError):
        unpack_export(source, tmp_path)


def test_offsite_login_rejected(config):
    config["login_url"] = "https://attacker.example/login"
    with pytest.raises(CollectionError):
        validate_config(config)



def test_live_locator_waits_for_async_element_then_checks_uniqueness():
    """Navigation is async: an immediate count() would incorrectly report missing."""
    from tatemono_map.cloud.collector import only
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        try:
            page=browser.new_page()
            page.set_content('<div id="root"></div>')
            page.evaluate("setTimeout(() => { const node = document.createElement('button'); node.id = 'later'; node.textContent = 'ready'; document.getElementById('root').appendChild(node); }, 50)")
            assert only(page.locator('#later'), 'company_search').inner_text() == 'ready'
        finally:
            browser.close()


def test_ui_locator_errors_have_safe_stage_codes():
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from tatemono_map.cloud.collector import only
    class Locator:
        def __init__(self, count, missing=False):
            self.first=self
            self._count=count
            self.missing=missing
        def wait_for(self, **kwargs):
            if self.missing: raise PlaywrightTimeoutError("private page and URL must not leak")
        def count(self): return self._count
    with pytest.raises(CollectionError, match='^ulucks_ui_company_link_missing$'):
        only(Locator(0, True), 'company_link')
    with pytest.raises(CollectionError, match='^ulucks_ui_area_checkbox_ambiguous$'):
        only(Locator(2), 'area_checkbox')
