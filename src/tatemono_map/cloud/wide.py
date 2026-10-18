"""Kitakyushu parent/child selection observed on the live member UI."""
from __future__ import annotations

import re
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urljoin

from tatemono_map.cloud import collector as c

from tatemono_map.ulucks_geography import AREA_LABELS, municipality_of


class CompanyCatalog(list):
    def __init__(self, entries, excluded, counts):
        super().__init__(entries)
        self.excluded=excluded
        self.counts=counts


from dataclasses import dataclass

# Identical, observed 43-character permission notice on actual companies 2/3.
# Unknown empty/error pages remain failures; they must never become zero stock.
ACCESS_NOTICE_SHA256=frozenset({'cbd17c56ae8a2538ec479ba3896c1d0255f145ee5ac49846e72221e4f201af00'})

@dataclass(frozen=True)
class CompanyUnavailable:
    evidence: dict
    code: str = 'access_request_required'

def access_unavailable(page):
    import hashlib
    if page.locator('form,input[type=checkbox],input[type=password]').count():
        return None
    for node in page.get_by_text(re.compile('申請')).all():
        if not node.evaluate("el=>!el.closest('a,nav,header,aside')"):continue
        text=c.normal(node.inner_text())
        fingerprint=hashlib.sha256(text.encode()).hexdigest()
        if fingerprint in ACCESS_NOTICE_SHA256:
            return CompanyUnavailable({'observed_url':page.url,'notice':text,'notice_sha256':fingerprint,
                'request_sent':False,'observed_at':datetime.now(timezone.utc).isoformat()})
    return None


def complete_catalog(current: CompanyCatalog, previous: list[dict]) -> CompanyCatalog:
    """Only the current positive-count census authorizes a collection.

    Previously verified routes validate history but never reintroduce a zero,
    blank or removed company. Its existing SQLite snapshot remains untouched.
    """
    for entry in previous:
        company_id=entry.get('company_id','')
        parsed=urlsplit(entry.get('search_url',''))
        if (not re.fullmatch('[0-9]+',company_id) or parsed.scheme!='https'
            or parsed.netloc!=urlsplit(c.ORIGIN).netloc or parsed.path.rstrip('/')!='/company/lists/'+company_id
            or parsed.query or parsed.fragment):
            raise c.CollectionError('previous_company_catalog_invalid')
    absent=sorted({x['company_id'] for x in previous}-{x['company_id'] for x in current},key=int)
    return CompanyCatalog(list(current),current.excluded,
        {**current.counts,'prior_route_checks':0,'unavailable_previous_ids':absent})


def company_catalog(page, previous_verified_ids=()) -> list[dict]:
    """Enumerate actual TD routes and actual index pagination; never scan IDs."""
    pending = []
    visited = set()
    companies = {}
    excluded={}
    census={'listed_rows':0,'zero_without_route':0,'other_without_route':0,'request_required':0,'positive_count':0}
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
        header=c.only(page.locator('th,td').filter(has_text=re.compile(r'^\s*物件数\s*$')),'company_count_header')
        table=header.locator('xpath=ancestor::table[1]')
        column=header.evaluate('el=>el.cellIndex')
        for row in table.locator('tr').all():
            cells=row.locator(':scope > td')
            if cells.count()<=column:continue
            census['listed_rows']+=1
            cell=cells.nth(column)
            value=c.normal(cell.inner_text()).replace(',','')
            raw=cell.get_attribute('data-href')
            url=urljoin(page.url,raw or '')
            parsed=urlsplit(url)
            match=re.fullmatch(r'/company/(lists|request)/([0-9]+)/?',parsed.path) if raw else None
            if raw and (parsed.scheme!='https' or parsed.netloc!=urlsplit(c.ORIGIN).netloc or not match or parsed.query or parsed.fragment):
                raise c.CollectionError('company_catalog_unexpected_target')
            company_id=match[2] if match else None
            key=company_id or 'row-'+str(census['listed_rows'])
            if value.isdigit() and int(value)>0:
                census['positive_count']+=1
                if not match or match[1]!='lists':
                    excluded[key]={'company_id':company_id,'status':'positive_route_unavailable','listed_count':int(value)}
                    continue
                if company_id in companies and companies[company_id]['search_url']!=url:
                    raise c.CollectionError('company_catalog_conflicting_routes')
                companies[company_id]={'company_id':company_id,'search_url':url,'listed_count':int(value)}
            else:
                status='zero_count' if value.isdigit() and int(value)==0 else 'blank_count' if not value else 'request_required' if match and match[1]=='request' else 'invalid_count'
                if status=='invalid_count':raise c.CollectionError('company_index_count_unrecognized')
                census['zero_without_route' if status=='zero_count' else 'other_without_route']+=1
                excluded[key]={'company_id':company_id,'status':status,'company_name':c.normal(cells.nth(0).inner_text())}
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
    census['request_required']=sum(x['status']=='request_required' for x in excluded.values())
    census['collectable_companies']=len(companies)
    print('ULUCKS_WIDE_SAFE='+json.dumps({'stage':'catalog','company_count':len(companies),'pages':len(visited),**census}),flush=True)
    return CompanyCatalog(sorted(companies.values(), key=lambda value: int(value['company_id'])),list(excluded.values()),census)


def area_of(address: str) -> str | None:
    return municipality_of(address)


def set_checked(control, wanted: bool) -> None:
    if control.is_checked() == wanted:
        return
    if control.is_visible():
        try:
            control.set_checked(wanted, timeout=5000)
        except Exception:
            pass
    if control.is_checked() != wanted:
        label = control.evaluate_handle('el => el.labels?.length === 1 ? el.labels[0] : null').as_element()
        if label is None:
            raise c.CollectionError('wide_area_associated_label_missing') from None
        label.click(timeout=7500)
    if control.is_checked() != wanted:
        raise c.CollectionError('wide_area_checked_state_mismatch')


def checkbox(locator, stage):
    # Custom-styled native inputs can be hidden while their real labels are
    # visible. Inspect their DOM identity; interact only through Playwright's
    # native check or the actual associated label, then verify checked state.
    from playwright.sync_api import TimeoutError
    try:locator.first.wait_for(state='attached',timeout=30000)
    except TimeoutError:raise c.CollectionError('ulucks_ui_'+stage+'_missing') from None
    if locator.count()!=1 or locator.get_attribute('type')!='checkbox':
        raise c.CollectionError('wide_checkbox_identity_changed')
    return locator


def group_form(page):
    parent = checkbox(page.get_by_label('北九州', exact=True), 'kitakyushu_parent')
    form = c.only(parent.locator('xpath=ancestor::form[1]'), 'search_form')
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


def company_heading(page):
    pattern=re.compile(r'物件検索\s*[（(](?!\s*ALL\s*[）)])[^）)]+[）)]',re.I)
    actual=page.locator('#search_list_header .f_left')
    return c.only(actual if actual.count() else page.get_by_text(pattern),'company_title')


def search(page, root: Path, company: dict) -> int:
    # Normalize the actual DOM and expected label identically. Regex locators
    # see raw full-width spaces, unlike the label extracted after NFKC.
    heading=company_heading(page)
    title=re.compile(r'物件検索\s*\(\s*'+re.escape(c.normal(company['company_label']))+r'\s*\)')
    if not title.search(c.normal(heading.inner_text())):
        raise c.CollectionError('company_search_heading_identity_changed')
    parent=page.get_by_label('北九州',exact=True)
    if parent.count()==1 and not parent.is_visible():
        label=parent.evaluate_handle('el=>el.labels?.length===1?el.labels[0]:null').as_element()
        if label is not None and not label.is_visible():
            # The live UI collapses the next company's search panel after a
            # successful search while retaining checked values. Its actual
            # company heading opens it; no synthetic URL or forced DOM change.
            heading.click(timeout=7500)
            label.wait_for_element_state('visible',timeout=10000)
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
        set_checked(checkbox(group.get_by_label(label, exact=True), 'wide_child'), True)
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
    heading=company_heading(page)
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
            previous=config.get('previous_verified_companies',[])
            catalog = complete_catalog(company_catalog(page,[x['company_id'] for x in previous]),previous)
            on_company(None, catalog)
            for target in catalog:
                if on_company(target,None) is True:
                    continue  # Explicitly approved, still-active verified snapshot.
                folder=root/target['company_id']
                folder.mkdir(parents=True,exist_ok=True)
                result=None
                for attempt in range(2):
                    try:
                        response = page.goto(target['search_url'],wait_until='domcontentloaded',timeout=45000)
                        if response is None or response.status != 200 or page.url.rstrip('/') != target['search_url'].rstrip('/'):
                            raise c.CollectionError('company_discovered_route_navigation_failed')
                        unavailable=access_unavailable(page)
                        if unavailable is not None:
                            result=unavailable
                            break
                        one=dict(config,**target,company_label=observed_company_label(page))
                        count=search(page,folder,one)
                        if count>int(config.get('max_rows',5000)):
                            raise c.CollectionError('ulucks_result_count_exceeds_limit')
                        if count==0:
                            if search(page,folder,one)!=0:raise c.CollectionError('ulucks_zero_result_not_stable')
                            result=c.Collected([],0,True,{'search_counts':[0,0],'scope_verified':True})
                        else:
                            # Compare the actual print link to the company route
                            # observed in this census; never synthesize a PDF URL.
                            action=c.only(page.get_by_role('link',name=c.PRINT_LABEL),'print_action')
                            print_url=urlsplit(urljoin(page.url,action.get_attribute('href') or ''))
                            match=re.fullmatch(r'/pdf/companys/([0-9]+)/?',print_url.path)
                            if print_url.netloc!=urlsplit(c.ORIGIN).netloc or not match or match[1]!=target['company_id']:
                                raise c.CollectionError('company_print_target_mismatch')
                            paths,evidence=c._capture_print(page,folder)
                            result=c.Collected(paths,count,False,{**evidence,'search_counts':[count],'scope_verified':True})
                        result.evidence.update(acquired_at=datetime.now(timezone.utc).isoformat(),area_labels=list(AREA_LABELS),company_id=target['company_id'])
                        break
                    except Exception as exc:
                        error=exc if isinstance(exc,c.CollectionError) else c.CollectionError('company_acquisition_failed')
                        # Private diagnostics contain no cookies or input values.
                        diagnostic=folder/('failure-'+str(attempt)+'.json')
                        state={'company_id':target['company_id'],'requested_url':target['search_url'],
                            'observed_url':page.url,'code':str(error),'attempt':attempt+1}
                        try:
                            if page.locator('input[type=password]').count()==0:
                                state['dom']=page.locator('form,h1,h2,h3,table').evaluate_all("els=>els.map(el=>({tag:el.tagName,text:el.innerText,controls:Array.from(el.querySelectorAll('input,button,select')).map(c=>({tag:c.tagName,type:c.type,name:c.name,checked:c.checked}))}))")
                                picture=folder/('failure-'+str(attempt)+'.png')
                                page.screenshot(path=str(picture),full_page=True)
                        except Exception:pass
                        diagnostic.write_text(json.dumps(state,ensure_ascii=False))
                        # Retry only transient browser/navigation/transport failures.
                        transient=str(error) in ('company_acquisition_failed','company_discovered_route_navigation_failed','ulucks_original_pdf_not_received')
                        if not transient or attempt==1:
                            error.diagnostic_files=list(folder.glob('failure-*'))
                            on_company(target,error)
                            break
                if result is None:continue
                if isinstance(result,CompanyUnavailable):
                    on_company(target,result)
                    continue
                for popup in context.pages:
                    if popup != page:
                        popup.close()
                # The verified PDF is already on disk. Release the browser PDF
                # viewer before parsing while keeping the single login session.
                on_company(one,result)
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
