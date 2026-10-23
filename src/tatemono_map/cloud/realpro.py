"""RealPro's observed member UI; credentials and response URLs stay in memory."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from tatemono_map.cloud.collector import CollectionError
from tatemono_map.ulucks_geography import municipality_of

ORIGIN = 'https://www.realnetpro.com'
COMPANY = '大東建託パートナーズ 小倉営業所'
COMPANY_ID = '15974'


def login(page, credentials):
    page.goto(ORIGIN + '/index.php', wait_until='domcontentloaded', timeout=60000)
    form = page.locator('#login_form')
    password = form.locator('#password_input[name="pass"]')
    if password.is_visible():
        identifier = form.locator('#login_input[name="id"]')
        if identifier.count() != 1 or password.count() != 1:
            raise CollectionError('realpro_login_dom_changed')
        identifier.fill(credentials['username'])
        password.fill(credentials['password'])
        buttons = form.locator('button,input[type=submit],input[type=button],input[type=image],a').filter(visible=True)
        choices = []
        for button in buttons.all():
            label = ' '.join([button.inner_text(), *(button.get_attribute(a) or '' for a in ('value','alt','aria-label','title'))])
            if 'ログイン' in [re.sub(r'\s+', '', x) for x in label.split()]:
                choices.append(button)
        if len(choices) != 1:
            raise CollectionError('realpro_login_action_ambiguous')
        choices[0].click(timeout=30000)
        try:
            page.wait_for_url('**/main.php*', wait_until='domcontentloaded', timeout=60000)
        except Exception:
            raise CollectionError('realpro_login_not_confirmed') from None
        page.wait_for_timeout(800)
    later = page.get_by_text('あとで連携する', exact=False)
    if later.count() == 1 and later.is_visible():
        later.click()
        page.get_by_text('連携画面をとじる', exact=False).click()
    if urlsplit(page.url).path != '/main.php' or page.locator('input[type=password]:visible').count():
        raise CollectionError('realpro_login_not_confirmed')
    page.get_by_role('link', name='管理会社一覧', exact=True).filter(visible=True).click()
    page.locator('#company_place').wait_for(state='attached', timeout=30000)


def choose(page, company_id, label):
    link = page.get_by_role('link', name=label, exact=True)
    if link.count() != 1 or link.get_attribute('id') != company_id:
        raise CollectionError('realpro_company_identity_changed')
    link.click()
    page.locator('input.city_check').first.wait_for(state='attached', timeout=30000)
    regions = page.locator('input.city_check').evaluate_all(
        'els=>els.map(e=>({value:e.value,label:e.parentElement.textContent.trim()}))')
    wanted = [r for r in regions if municipality_of(r['label'])]
    if not wanted:
        return []
    for region in regions:
        page.locator('input.city_check[value="' + region['value'] + '"]').set_checked(region in wanted)
    # The city controls also select the source's child town-code controls.
    selected = page.locator('input.city_check:checked').evaluate_all('els=>els.map(e=>e.value)')
    if sorted(selected) != sorted(r['value'] for r in wanted):
        raise CollectionError('realpro_region_selection_mismatch')
    company = page.locator('#company_search input[name=company_id]').input_value()
    if company != company_id:
        raise CollectionError('realpro_selected_company_mismatch')
    if page.locator('#company_search input[name="town_code[]"]:checked').count() == 0:
        raise CollectionError('realpro_selected_towns_empty')
    return wanted


def room_count(path):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    ids = set()
    for page in reader.pages:
        for ref in page.get('/Annots', []):
            annotation = ref.get_object()
            action = annotation.get('/A', {})
            uri = str(action.get('/URI', ''))
            parsed = urlsplit(uri)
            if parsed.hostname == 'www.realnetpro.com' and parsed.path == '/room_detail.php':
                values = parse_qs(parsed.query).get('id', [])
                if len(values) == 1 and values[0].isdigit():
                    ids.add(values[0])
    if not ids or not reader.pages:
        raise CollectionError('realpro_pdf_has_no_verified_rooms')
    return len(ids), len(reader.pages)


def acquire(page, context, root, company_id):
    root.mkdir(parents=True, exist_ok=True)
    path = root / ('realpro-' + company_id + '.pdf')
    responses, failures, downloads = [], [], []
    def register_download(popup):
        popup.on('download', downloads.append)
    def receive(response):
        parsed = urlsplit(response.url)
        if parsed.hostname != 'www.realnetpro.com' or parsed.path != '/common/pdf_list.php':
            return
        if response.request.method != 'POST':
            return
        try:
            if response.status != 200:
                failures.append('realpro_pdf_http_failed'); return
            responses.append(response)
        except Exception:
            failures.append('realpro_pdf_response_read_failed')
    context.on('response', receive)
    page.on('download', downloads.append)
    context.on('page', register_download)
    try:
        page.locator('img.print_button_image[src="./img/DL_list_company.jpg"]').click()
        deadline = time.monotonic() + 180
        while not failures and time.monotonic() < deadline:
            if downloads:
                downloads[0].save_as(path); break
            if responses:
                try:
                    response = responses.pop(0)
                    response.finished()
                    path.write_bytes(response.body()); break
                except Exception:
                    pass  # Attachment responses may instead become downloads.
            page.wait_for_timeout(100)
        if not path.exists():
            raise CollectionError(failures[0] if failures else 'realpro_pdf_not_received')
        if not path.read_bytes().startswith(b'%PDF-') or not 1000 < path.stat().st_size < 100*1024*1024:
            raise CollectionError('realpro_export_response_not_pdf')
        count, pages = room_count(path)
        return path, {'pdf_pages':pages, 'expected_rows':count,
            'pdf_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'acquired_at':datetime.now(timezone.utc).isoformat()}
    finally:
        context.remove_listener('response', receive)
        context.remove_listener('page', register_download)
        page.remove_listener('download', downloads.append)
        for popup in context.pages:
            if popup != page:
                popup.close()


def collect(config, credentials, root):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        options = {'headless':True}
        if os.environ.get('TATEMONO_CHROMIUM_EXECUTABLE'):
            options['executable_path'] = os.environ['TATEMONO_CHROMIUM_EXECUTABLE']
        browser = p.chromium.launch(**options)
        try:
            context = browser.new_context(accept_downloads=True, locale='ja-JP', viewport={'width':1536,'height':900})
            page = context.new_page()
            login(page, credentials)
            regions = choose(page, config['company_id'], config['company_label'])
            if config['company_id'] == COMPANY_ID and {r['label'] for r in regions} != {
                '北九州市門司区','北九州市小倉北区','北九州市小倉南区','田川市','行橋市','京都郡苅田町','築上郡築上町'}:
                raise CollectionError('realpro_first_company_scope_changed')
            if not regions:
                raise CollectionError('realpro_company_has_no_target_regions')
            pdf, evidence = acquire(page, context, root, config['company_id'])
            evidence.update(company_id=config['company_id'], regions=regions, scope_verified=True)
            return pdf, evidence
        finally:
            browser.close()
