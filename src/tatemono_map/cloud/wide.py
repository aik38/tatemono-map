"""Kitakyushu parent/child selection observed on the live member UI."""
from __future__ import annotations

import re
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urljoin

from tatemono_map.cloud import collector as c

AREA_LABELS = ('小倉北区','小倉南区','八幡東区','八幡西区','若松区','戸畑区','門司区',
    '中間市','遠賀郡','京都郡','行橋市','築上郡','豊前市','直方市','鞍手郡','田川郡',
    '田川市','宗像市','宮若市','飯塚市','嘉穂郡','嘉麻市')


class CompanyCatalog(list):
    def __init__(self, entries, excluded, counts):
        super().__init__(entries)
        self.excluded=excluded
        self.counts=counts


def complete_catalog(current: CompanyCatalog, previous: list[dict]) -> CompanyCatalog:
    """Recheck only generation-pinned previously observed routes when absent.

    A company can lose its index link after its final listing disappears. Its
    prior verified route still needs two live zero searches; absence is not zero.
    """
    known={entry['company_id'] for entry in current}
    requested={entry['company_id'] for entry in current.excluded}
    extra=[]
    for entry in previous:
        company_id=entry.get('company_id','')
        parsed=urlsplit(entry.get('search_url',''))
        if (not re.fullmatch('[0-9]+',company_id) or parsed.scheme!='https'
            or parsed.netloc!=urlsplit(c.ORIGIN).netloc or parsed.path.rstrip('/')!='/company/lists/'+company_id
            or parsed.query or parsed.fragment):
            raise c.CollectionError('previous_company_catalog_invalid')
        if company_id in requested:
            raise c.CollectionError('previous_company_now_requires_access_request')
        if company_id not in known:
            extra.append({'company_id':company_id,'search_url':entry['search_url']})
            known.add(company_id)
    return CompanyCatalog(sorted(list(current)+extra,key=lambda x:int(x['company_id'])),current.excluded,
        {**current.counts,'prior_route_checks':len(extra)})


def company_catalog(page) -> list[dict]:
    """Enumerate actual TD routes and actual index pagination; never scan IDs."""
    pending = []
    visited = set()
    companies = {}
    excluded={}
    census={'listed_rows':0,'zero_without_route':0,'other_without_route':0,'request_required':0}
    while True:
        here = page.url
        if here in visited:
            raise c.CollectionError('company_pagination_loop')
        visited.add(here)
        if len(visited) > 100:
            raise c.CollectionError('company_pagination_budget_exceeded')
        targets = page.locator('td[data-href]')
        targets.first.wait_for(state='visible',timeout=30000)
        if targets.count() == 0:
            raise c.CollectionError('company_catalog_empty')
        for cell in targets.all():
            url = urljoin(page.url, cell.get_attribute('data-href') or '')
            parsed = urlsplit(url)
            denied=re.fullmatch(r'/company/request/([0-9]+)/?',parsed.path)
            if parsed.netloc == urlsplit(c.ORIGIN).netloc and parsed.scheme=='https' and denied and not parsed.query and not parsed.fragment:
                excluded[denied[1]]={'company_id':denied[1],'status':'request_required'}
                continue
            match = re.fullmatch(r'/company/lists/([0-9]+)/?',parsed.path)
            if parsed.netloc != urlsplit(c.ORIGIN).netloc or not match or parsed.query or parsed.fragment:
                raise c.CollectionError('company_catalog_unexpected_target')
            company_id = match[1]
            if company_id in companies and companies[company_id]['search_url'] != url:
                raise c.CollectionError('company_catalog_conflicting_routes')
            companies[company_id] = {'company_id':company_id,'search_url':url}
        header=c.only(page.locator('th,td').filter(has_text=re.compile(r'^\s*物件数\s*$')),'company_count_header')
        table=header.locator('xpath=ancestor::table[1]')
        column=header.evaluate('el=>el.cellIndex')
        for row in table.locator('tr').all():
            cells=row.locator(':scope > td')
            if cells.count()<=column:
                continue
            census['listed_rows']+=1
            cell=cells.nth(column)
            if cell.get_attribute('data-href'):
                continue
            value=c.normal(cell.inner_text()).replace(',','')
            if value.isdigit() and int(value)==0:
                census['zero_without_route']+=1
            elif value.isdigit() and int(value)>0:
                raise c.CollectionError('company_positive_count_without_observed_route')
            else:
                census['other_without_route']+=1
        # Follow only pagination URLs actually present on this index. Avoid
        # unrelated navigation and never synthesize a page number or company ID.
        for control in page.locator('a[href], [data-href]').all():
            label = c.normal(control.inner_text())
            if not re.fullmatch(r'(?:[0-9]+|次(?:へ|のページ)?|前(?:へ|のページ)?|[»«›‹]|Next|Previous)',label,re.I):
                continue
            url = urljoin(page.url, control.get_attribute('href') or control.get_attribute('data-href') or '')
            parsed = urlsplit(url)
            if parsed.netloc == urlsplit(c.ORIGIN).netloc and parsed.path.rstrip('/') == '/company' and url not in visited and url not in pending:
                pending.append(url)
        for control in page.get_by_role('button').all():
            if re.fullmatch(r'(?:次(?:へ|のページ)?|Next|[»›])',c.normal(control.inner_text()),re.I) and control.is_enabled():
                raise c.CollectionError('company_pagination_button_requires_review')
        if not pending:
            break
        response = page.goto(pending.pop(0),wait_until='domcontentloaded',timeout=45000)
        if response is None or response.status != 200:
            raise c.CollectionError('company_pagination_navigation_failed')
    if '8' not in companies or '26' not in companies:
        raise c.CollectionError('company_catalog_known_companies_missing')
    census['request_required']=len(excluded)
    census['collectable_companies']=len(companies)
    print('ULUCKS_WIDE_SAFE='+json.dumps({'stage':'catalog','company_count':len(companies),'pages':len(visited),**census}),flush=True)
    return CompanyCatalog(sorted(companies.values(), key=lambda value: int(value['company_id'])),list(excluded.values()),census)


def area_of(address: str) -> str | None:
    value = c.normal(address).replace(' ', '')
    if value.startswith('福岡県'):
        value = value[3:]
    for label in AREA_LABELS:
        prefix = '北九州市' + label if label.endswith('区') else label
        if value.startswith(prefix):
            if label.endswith('郡'):
                town = re.match(re.escape(label) + r'[^0-9]+?[町村]', value)
                return town[0] if town else None
            return prefix
    return None


def set_checked(control, wanted: bool) -> None:
    if control.is_checked() == wanted:
        return
    try:
        control.set_checked(wanted, timeout=5000)
    except Exception:
        if control.is_checked() != wanted:
            label = control.evaluate_handle('el => el.labels?.length === 1 ? el.labels[0] : null').as_element()
            if label is None:
                raise c.CollectionError('wide_area_associated_label_missing') from None
            label.click(timeout=7500)
    if control.is_checked() != wanted:
        raise c.CollectionError('wide_area_checked_state_mismatch')


def group_form(page):
    form, _ = c._search_form(page)
    parent = c.only(form.get_by_label('北九州', exact=True), 'kitakyushu_parent')
    if parent.get_attribute('type') != 'checkbox':
        raise c.CollectionError('wide_parent_not_checkbox')
    # Smallest actual ancestor containing the parent and all 22 observed areas.
    for candidate in parent.locator('xpath=ancestor::div').all():
        checks = candidate.locator('input[type="checkbox"]')
        if checks.count() != len(AREA_LABELS) + 1:
            continue
        labels = checks.evaluate_all("els => els.flatMap(el => Array.from(el.labels||[]).map(l=>l.innerText.trim()))")
        if len(labels) == len(AREA_LABELS) + 1 and set(labels) == set(AREA_LABELS) | {'北九州'}:
            return form, parent, candidate
    raise c.CollectionError('wide_parent_children_contract_changed')


def search(page, root: Path, company: dict) -> int:
    title = re.compile(r'物件検索\s*[（(]\s*' + re.escape(company['company_label']) + r'\s*[）)]')
    c.only(page.get_by_text(title), 'company_title')
    form, parent, group = group_form(page)
    for field in form.locator('input[type="text"], input[type="search"]').all():
        if field.input_value().strip():
            raise c.CollectionError('ulucks_nonempty_search_text_requires_review')
    # Clear only actually checked controls outside the verified region group.
    for check in form.locator('input[type="checkbox"]').all():
        if not check.is_checked():
            continue
        in_group = group.evaluate('(el, other) => el.contains(other)', check.element_handle())
        if not in_group:
            set_checked(check, False)
    set_checked(parent, True)
    for label in AREA_LABELS:
        set_checked(c.only(group.get_by_label(label, exact=True), 'wide_child'), True)
    if form.locator('input[type="checkbox"]:checked').count() != len(AREA_LABELS) + 1 or any(
        not group.get_by_label(label, exact=True).is_checked() for label in ('北九州',) + AREA_LABELS
    ):
        raise c.CollectionError('wide_area_not_exclusive')
    button = c._observed_search_action(page, root, form)
    submission = form.evaluate("el => ({url:el.action,method:el.method.toUpperCase()})")
    with page.expect_response(lambda r: r.url == submission['url'] and r.request.method == submission['method']
        and r.request.resource_type == 'document' and r.frame == page.main_frame, timeout=60000) as pending:
        button.click()
    response = pending.value
    if response.status != 200:
        raise c.CollectionError('ulucks_search_http_failed')
    response.finished()
    page.wait_for_load_state('domcontentloaded')
    page.wait_for_function(r"() => /検索結果\s*[\d,]+\s*件中/.test((document.body?.innerText||'').normalize('NFKC'))", timeout=45000)
    count=c._confirmed_result_count(c.normal(page.locator('body').inner_text()))
    c._append_ui_observation(root,'search_completed',{'result_count':count,'child_area_count':len(AREA_LABELS),'scope_verified':True})
    print('ULUCKS_WIDE_SAFE='+json.dumps({'stage':'search','result_count':count,'child_area_count':len(AREA_LABELS),'scope_verified':True}),flush=True)
    return count


def collect_with_page(page, config: dict, credentials: dict, root: Path) -> c.Collected:
    # Reuse the already proven login/company-navigation flow. Replace only its
    # narrow-area search operation for this single sequential session.
    original_search = c._search
    original_observe = c._observe_company_row
    catalog = []
    census={}
    excluded=[]
    def observe(page, row, root):
        observed=company_catalog(page)
        catalog.extend(observed)
        census.update(observed.counts)
        excluded.extend(observed.excluded)
        target = next(x for x in catalog if x['company_id'] == '8')
        if target['search_url'].rstrip('/') != config['search_url'].rstrip('/'):
            raise c.CollectionError('company_catalog_reviewed_route_changed')
        # The index may have pagination. Navigate using the exact discovered
        # route; the existing flow verifies the known company heading next.
        return [], {'stage':'company_row_observed','catalog_verified':True}
    c._search = lambda page, root: search(page, root, config)
    c._observe_company_row = observe
    try:
        narrow = dict(config, area_id='kokurakita',area_label='小倉北区',address_contains='小倉北区')
        result = c.collect_with_page(page, narrow, credentials, root)
        result.evidence['area_labels'] = list(AREA_LABELS)
        result.evidence['area_id'] = 'kitakyushu'
        result.evidence['companies'] = catalog
        result.evidence['company_census'] = census
        result.evidence['excluded_companies'] = excluded
        return result
    finally:
        c._search = original_search
        c._observe_company_row = original_observe


def observed_company_label(page) -> str:
    # The sidebar also says 物件検索(ALL). Read the actual company title,
    # excluding that observed navigation label without assuming an HTML tag.
    pattern=re.compile(r'物件検索\s*[（(](?!\s*ALL\s*[）)])[^）)]+[）)]',re.I)
    heading=c.only(page.get_by_text(pattern),'company_title')
    match=re.search(r'物件検索\s*[（(]\s*([^）)]+?)\s*[）)]',c.normal(heading.inner_text()))
    if not match:
        raise c.CollectionError('company_discovered_heading_missing')
    return match[1]


def collect_all(config: dict, credentials: dict, root: Path, on_company) -> list[dict]:
    """One login, a complete live catalog, sequential per-company acquisition."""
    from playwright.sync_api import sync_playwright
    c.validate_config(config)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True,executable_path=os.environ.get('TATEMONO_CHROMIUM_EXECUTABLE'))
        context = browser.new_context(accept_downloads=True,locale='ja-JP')
        context.set_default_timeout(30000)
        page = context.new_page()
        index = None
        try:
            c.login_to_company_index(page,credentials)
            index = page.url
            catalog = complete_catalog(company_catalog(page),config.get('previous_verified_companies',[]))
            on_company(None, catalog)
            for target in catalog:
                on_company(target,None)
                response = page.goto(target['search_url'],wait_until='domcontentloaded',timeout=45000)
                if response is None or response.status != 200 or page.url.rstrip('/') != target['search_url'].rstrip('/'):
                    raise c.CollectionError('company_discovered_route_navigation_failed')
                one = dict(config,**target,company_label=observed_company_label(page))
                folder = root / target['company_id']
                folder.mkdir(parents=True,exist_ok=True)
                count = search(page,folder,one)
                if count > int(config.get('max_rows',5000)):
                    raise c.CollectionError('ulucks_result_count_exceeds_limit')
                if count == 0:
                    if search(page,folder,one) != 0:
                        raise c.CollectionError('ulucks_zero_result_not_stable')
                    result = c.Collected([],0,True,{'search_counts':[0,0],'scope_verified':True})
                else:
                    paths,evidence = c._capture_print(page,folder)
                    result = c.Collected(paths,count,False,{**evidence,'search_counts':[count],'scope_verified':True})
                result.evidence.update(acquired_at=datetime.now(timezone.utc).isoformat(),area_labels=list(AREA_LABELS),company_id=target['company_id'])
                on_company(one,result)
                for popup in context.pages:
                    if popup != page:
                        popup.close()
            return catalog
        except c.CollectionError:
            raise
        except Exception:
            raise c.CollectionError('all_companies_operation_failed') from None
        finally:
            try:
                if index and not page.is_closed():
                    page.goto(index,wait_until='domcontentloaded',timeout=15000)
                    logout=page.get_by_role('link',name='ログアウト',exact=True).or_(page.get_by_role('button',name='ログアウト',exact=True))
                    if logout.count()==1:
                        logout.click(timeout=5000)
            except Exception:
                pass
            browser.close()
