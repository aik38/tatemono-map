"""RealPro's observed member UI; credentials and response URLs stay in memory."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, urljoin

from tatemono_map.cloud.collector import CollectionError
from tatemono_map.ulucks_geography import municipality_of

ORIGIN = 'https://www.realnetpro.com'
COMPANY = '大東建託パートナーズ 小倉営業所'
COMPANY_ID = '15974'


def login(page, credentials):
    route = credentials.get('login_route', 'rnp')
    if route not in ('rnp','bb_store','bb_personal'):
        raise CollectionError('realpro_login_route_invalid')
    if route != 'rnp':
        return login_bb(page,credentials,route)
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
    return finish_login(page)


# Owner approval on 2026-10-24 applies only to the verified 2021-08-02 terms.
# A changed text must be reviewed; never accept a different revision silently.
APPROVED_TERMS_SHA256 = "fc622fe1bb3c3053a255c441ffd438edd9fa38dbce43afd3c975ca7e19bd6165"


def accept_approved_terms(page):
    box = page.locator('#term_contents_box')
    if box.count() != 1:
        raise CollectionError('realpro_terms_dom_changed')
    content = re.sub(r'\s+', '', box.inner_text())
    fingerprint = hashlib.sha256(content.encode()).hexdigest()
    if fingerprint != APPROVED_TERMS_SHA256:
        raise CollectionError('realpro_terms_changed_owner_review_required')
    box.evaluate('(element) => { element.scrollTop = element.scrollHeight; }')
    page.wait_for_timeout(200)
    page.locator('#agree').click(timeout=10000)
    page.wait_for_timeout(800)


def finish_login(page):
    """Pass only known, owner-approved gates, then require the company list."""
    text = page.locator('body').inner_text()
    if 'ご利用に関する同意のお願い' in text or (
            'サービス利用規約' in text and 'に同意する' in text):
        accept_approved_terms(page)
        text = page.locator('body').inner_text()
    start = page.get_by_text('「リアプロBB+仲介」を利用する', exact=True)
    if start.count() == 1 and start.is_visible():
        start.click()
        page.wait_for_load_state('domcontentloaded')
        page.wait_for_timeout(800)
        text = page.locator('body').inner_text()
        if 'ご利用に関する同意のお願い' in text:
            raise CollectionError('realpro_terms_consent_required')
    later = page.get_by_text('あとで連携する', exact=False)
    if later.count() == 1 and later.is_visible():
        later.click()
        page.get_by_text('連携画面をとじる', exact=False).click()
    if urlsplit(page.url).hostname != 'www.realnetpro.com' or urlsplit(page.url).path != '/main.php' or page.locator('input[type=password]:visible').count():
        raise CollectionError('realpro_login_not_confirmed')
    company_link = page.get_by_role('link', name=re.compile(r'管理会社\s*一覧')).filter(visible=True)
    if company_link.count() != 1:
        raise CollectionError('realpro_company_link_ambiguous')
    destination = urljoin(ORIGIN, company_link.get_attribute('href') or '')
    target = urlsplit(destination)
    if target.hostname != 'www.realnetpro.com' or target.path != '/main.php' or parse_qs(target.query) != {'method': ['company_list']}:
        raise CollectionError('realpro_company_link_changed')
    # Follow the observed link; a collapsed menu can keep it outside the viewport.
    page.goto(destination, wait_until='domcontentloaded', timeout=30000)
    page.locator('#company_place').wait_for(state='attached', timeout=30000)
    return page


def login_bb(page, credentials, route):
    """Use the observed legacy banner, preserving its redirect in memory only."""
    context = page.context
    page.goto(ORIGIN+'/index.php',wait_until='domcontentloaded',timeout=60000)
    banner = page.get_by_role('img',name='リアプロBBログインバナー',exact=True)
    banner.click()
    page.wait_for_timeout(800)
    page = context.pages[-1]
    if urlsplit(page.url).hostname != 'login.n-create.jp':
        raise CollectionError('realpro_bb_entry_origin_changed')
    page.locator('input[name=login_id]').wait_for(state='visible',timeout=30000)
    page.get_by_text('店舗アカウント' if route=='bb_store' else '個人アカウント',exact=True).click()
    page.locator('input[name=login_id]').fill(credentials['username'])
    page.locator('input[name=password]').fill(credentials['password'])
    page.get_by_role('button',name='ログイン',exact=True).click()
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        errors=page.get_by_role('alert').all_text_contents()
        if any('ログインIDまたはパスワードが間違っています' in s for s in errors):
            raise CollectionError('realpro_bb_credentials_rejected')
        if urlsplit(page.url).hostname != 'login.n-create.jp':
            break
        page.wait_for_timeout(200)
    else:
        raise CollectionError('realpro_bb_authentication_incomplete')
    # The final service remains responsible for authorizing this session.
    # Never synthesize redirect parameters or copy cookies between sessions.
    if urlsplit(page.url).hostname != 'www.realnetpro.com':
        page.goto(ORIGIN+'/main.php',wait_until='domcontentloaded',timeout=60000)
    return finish_login(page)


def _entries(value):
    return list(value.values()) if isinstance(value, dict) else list(value)


def choose(page, company_id, label):
    if not re.fullmatch(r'\d+', company_id):
        raise CollectionError('realpro_company_id_invalid')
    link = page.locator('.company_box a[id="' + company_id + '"]')
    if link.count() != 1 or re.sub(r'\s+', '', link.inner_text()) != re.sub(r'\s+', '', label):
        raise CollectionError('realpro_company_identity_changed')
    def selected_response(response):
        url = urlsplit(response.url)
        return (url.hostname == 'www.realnetpro.com' and url.path == '/ajax/get_list_area.php'
                and parse_qs(url.query).get('id') == [company_id]
                and response.request.method == 'GET')
    # The site's handler is on the enclosing company box, including empty links.
    with page.expect_response(selected_response, timeout=45000) as pending:
        link.locator('..').click(timeout=15000)
    response = pending.value
    if response.status != 200:
        raise CollectionError('realpro_company_area_http_failed')
    raw = response.text().strip()
    deadline = time.monotonic() + 30
    if raw == 'false':
        while time.monotonic() < deadline:
            if page.locator('#select_city').inner_text().strip() == '公開中の物件がありません':
                raise CollectionError('realpro_no_published_properties')
            page.wait_for_timeout(100)
        raise CollectionError('realpro_empty_company_not_confirmed')
    data = json.loads(raw)
    title = data.get('company_name', '').strip()
    if not title:
        raise CollectionError('realpro_company_area_name_missing')
    expected, towns = {}, set()
    for pref in _entries(data['pref']):
        for city in _entries(pref['city']):
            code = str(city['city_code'])
            if not re.fullmatch(r'\d{5}', code) or code in expected:
                raise CollectionError('realpro_company_area_codes_invalid')
            expected[code] = str(city['city_name']).strip()
            for town in _entries(city['town']):
                t = str(town['town_code'])
                if not re.fullmatch(r'\d{8}', t) or t[:5] != code:
                    raise CollectionError('realpro_company_area_towns_invalid')
                if code.startswith('40'): towns.add(t)
    while time.monotonic() < deadline:
        state = page.locator('#company_search').evaluate("""el=>({
            id:el.querySelector('input[name=company_id]')?.value,
            title:el.querySelector('.company_room_m')?.textContent.trim(),
            areaTitle:el.querySelector('#company_name')?.textContent.trim(),
            cities:Array.from(el.querySelectorAll('#select_city input.city_check')).map(e=>({value:e.value,label:e.parentElement.textContent.trim()})),
            towns:Array.from(el.querySelectorAll('#select_city input[name="town_code[]"]')).map(e=>e.value)
        })""")
        actual = {r['value']:r['label'] for r in state['cities']}
        if (state.get('id') == company_id and state.get('title') == title
                and state.get('areaTitle') == title and actual == expected
                and {t for t in state['towns'] if t.startswith('40')} == towns):
            break
        page.wait_for_timeout(100)
    else:
        raise CollectionError('realpro_selected_company_area_mismatch')
    regions = state['cities']
    wanted = [r for r in regions if re.fullmatch(r'40\d{3}', r['value'])]
    if not wanted: return []
    for region in regions:
        page.locator('#select_city input.city_check[value="' + region['value'] + '"]').set_checked(region in wanted)
    selected = page.locator('#select_city input.city_check:checked').evaluate_all('els=>els.map(e=>e.value)')
    selected_towns = page.locator('#select_city input[name="town_code[]"]:checked').evaluate_all('els=>els.map(e=>e.value)')
    if sorted(selected) != sorted(r['value'] for r in wanted):
        raise CollectionError('realpro_region_selection_mismatch')
    if not towns or set(selected_towns) != towns:
        raise CollectionError('realpro_selected_towns_mismatch')
    if (page.locator('#company_search input[name=company_id]').input_value() != company_id
            or page.locator('#company_search .company_room_m').inner_text().strip() != title
            or page.locator('#company_name').inner_text().strip() != title):
        raise CollectionError('realpro_selected_company_mismatch')
    return wanted


def discover(page):
    """Fresh Fukuoka catalog from the observed UI, including unavailable IDs."""
    page.goto(ORIGIN + '/main.php?method=company_list', wait_until='domcontentloaded', timeout=60000)
    prefs = page.locator('#company_place input[name="pref_code[]"]')
    values = prefs.evaluate_all('els=>els.map(e=>({value:e.value,checked:e.checked}))')
    if not any(v['value'] == '40' for v in values):
        raise CollectionError('realpro_fukuoka_filter_missing')
    for value in values:
        wanted = value['value'] == '40'
        if value['checked'] != wanted:
            page.locator('#company_place label').filter(
                has=page.locator('input[value="' + value['value'] + '"]')).click()
            page.wait_for_timeout(500)
    selected = prefs.evaluate_all('els=>els.filter(e=>e.checked).map(e=>e.value)')
    if selected != ['40']:
        raise CollectionError('realpro_fukuoka_filter_not_exclusive')
    page.locator('.company_box a[id]').first.wait_for(state='attached', timeout=30000)
    companies = page.locator('.company_box a[id]').evaluate_all(
        'els=>els.map(e=>({company_id:e.id,company_label:e.textContent.trim(),href:e.getAttribute("href")}))')
    if not companies or any(not re.fullmatch(r'\d+', c['company_id']) or c['href'] != '#' for c in companies):
        raise CollectionError('realpro_company_catalog_changed')
    if len({c['company_id'] for c in companies}) != len(companies):
        raise CollectionError('realpro_duplicate_company_id')
    return [dict(c, availability='available') for c in companies]


def room_count(path):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    ids = set()
    for page in reader.pages:
        for ref in page.get('/Annots', []):
            annotation = ref.get_object()
            action = annotation.get('/A', {})
            if hasattr(action, 'get_object'):
                action = action.get_object()
            uri = str(action.get('/URI', ''))
            parsed = urlsplit(uri)
            if parsed.hostname == 'www.realnetpro.com' and parsed.path == '/room_detail.php':
                values = parse_qs(parsed.query).get('id', [])
                if len(values) == 1 and values[0].isdigit():
                    ids.add(values[0])
    if not ids or not reader.pages:
        raise CollectionError('realpro_pdf_has_no_verified_rooms')
    return len(ids), len(reader.pages)


def acquire(page, context, root, company_id, *, on_download=None):
    root.mkdir(parents=True, exist_ok=True)
    path = root / ('realpro-' + company_id + '.pdf')
    responses, failures, downloads = [], [], []
    def receive_download(download):
        downloads.append(download)
    def register_download(popup):
        popup.on('download', receive_download)
    def receive(response):
        parsed = urlsplit(response.url)
        if parsed.hostname != 'www.realnetpro.com' or parsed.path != '/common/pdf_list.php':
            return
        if response.request.method != 'POST':
            return
        try:
            if response.status != 200:
                failures.append('realpro_pdf_http_failed'); return
        except Exception:
            failures.append('realpro_pdf_response_read_failed')
    def receive_finished(request):
        parsed = urlsplit(request.url)
        if (parsed.hostname != 'www.realnetpro.com' or parsed.path != '/common/pdf_list.php'
                or request.method != 'POST'):
            return
        # Attachment responses may never emit requestfinished. Their download
        # event is independent: never block it by waiting on response.finished().
        response = request.response()
        if response is not None and response.status == 200:
            responses.append(response)
    context.on('response', receive)
    context.on('requestfinished', receive_finished)
    page.on('download', receive_download)
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
                    path.write_bytes(response.body()); break
                except Exception:
                    pass  # Attachment responses may instead become downloads.
            page.wait_for_timeout(100)
        if not path.exists():
            raise CollectionError(failures[0] if failures else 'realpro_pdf_not_received')
        if not path.read_bytes().startswith(b'%PDF-') or not 1000 < path.stat().st_size < 100*1024*1024:
            raise CollectionError('realpro_export_response_not_pdf')
        if on_download is not None:
            on_download(path)
        count, pages = room_count(path)
        return path, {'pdf_pages':pages, 'expected_rows':count,
            'pdf_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'acquired_at':datetime.now(timezone.utc).isoformat()}
    finally:
        context.remove_listener('response', receive)
        context.remove_listener('requestfinished', receive_finished)
        context.remove_listener('page', register_download)
        page.remove_listener('download', receive_download)
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
            page = login(page, credentials)
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

