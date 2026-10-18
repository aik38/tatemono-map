import os
import pytest
from urllib.parse import parse_qs

from playwright.sync_api import sync_playwright

from tatemono_map.cloud.wide import AREA_LABELS, search
from tatemono_map.cloud.wide import company_catalog
from tatemono_map.cloud.wide import observed_company_label
from tatemono_map.cloud.collector import ORIGIN, COMPANY_LABEL


@pytest.mark.parametrize('hidden,collapsed',[(False,False),(True,False),(False,True)])
def test_full_parent_group_excludes_every_other_selected_area(tmp_path,hidden,collapsed):
    inputs=''.join(f'<label><input type="checkbox" name="area" value="{i}">{label}</label>' for i,label in enumerate(AREA_LABELS))
    body=f'''<meta charset="utf-8"><h2>物件検索（{COMPANY_LABEL}）</h2>
    <form method="post" action="{ORIGIN}/company/lists/8">
    <div><label><input type="checkbox" name="parent" value="north">北九州</label><div>{inputs}</div></div>
    <div><label><input type="checkbox" name="outside" value="fukuoka" checked>福岡市</label></div>
    <input type="submit" value="検索"></form>'''
    if hidden:body='<style>input[type=checkbox]{display:none}</style>'+body
    if collapsed:
        body=body.replace('<h2>', '<h2 onclick="document.querySelector(\'form\').style.display=\'block\'">')
        body=body.replace('<form method=', '<form style="display:none" method=')
    sent=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=os.environ.get('TATEMONO_CHROMIUM_EXECUTABLE'))
        page=browser.new_page()
        def route(r):
            if r.request.method=='POST':
                sent.append(parse_qs(r.request.post_data))
                r.fulfill(status=200,content_type='text/html; charset=utf-8',body='検索結果1045件中')
            else:
                r.fulfill(status=200,content_type='text/html; charset=utf-8',body=body)
        page.route(ORIGIN+'/**',route)
        page.goto(ORIGIN+'/company/lists/8')
        try:
            assert search(page,tmp_path,{'company_label':COMPANY_LABEL})==1045
            assert sent[0]['area']==[str(i) for i in range(22)]
            assert 'outside' not in sent[0]
            assert sent[0]['parent']==['north']
        finally:
            browser.close()


def test_company_census_follows_actual_pagination_and_td_routes():
    one='<meta charset="utf-8"><table><tr><th>会社名</th><th>物件数</th></tr><tr><td>架空甲社</td><td data-href="/company/lists/8">1</td></tr></table><a href="/company?page=2">2</a>'
    two='<meta charset="utf-8"><table><tr><th>会社名</th><th>物件数</th></tr><tr><td>架空乙社</td><td data-href="/company/lists/26">2</td></tr><tr><td>架空申請社</td><td data-href="/company/request/99">申請</td></tr><tr><td>架空ゼロ社</td><td>0</td></tr></table><a href="/company">前へ</a>'
    visited=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=os.environ.get('TATEMONO_CHROMIUM_EXECUTABLE'))
        page=browser.new_page()
        def route(r):
            if r.request.resource_type=='document':
                visited.append(r.request.url)
            r.fulfill(status=200,content_type='text/html; charset=utf-8',body=two if '?page=2' in r.request.url else one)
        page.route(ORIGIN+'/**',route)
        try:
            page.goto(ORIGIN+'/company')
            catalog=company_catalog(page)
            assert [x['company_id'] for x in catalog]==['8','26']
            assert [(x['company_id'],x['status']) for x in catalog.excluded]==[('99','request_required'),(None,'zero_count')]
            assert catalog.counts['zero_without_route']==1
            assert visited==[ORIGIN+'/company',ORIGIN+'/company?page=2']
        finally:
            browser.close()


def test_company_heading_excludes_observed_all_properties_sidebar():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=os.environ.get('TATEMONO_CHROMIUM_EXECUTABLE'))
        page=browser.new_page()
        try:
            page.set_content('<a>物件検索(ALL)</a><h2>物件検索（架空甲社）</h2>')
            assert observed_company_label(page)=='架空甲社'
        finally:
            browser.close()


def test_explicit_access_notice_is_retained_as_unavailable_not_an_empty_snapshot(monkeypatch):
    import hashlib
    from tatemono_map.cloud import wide
    notice='この架空会社の物件は許可申請後に公開されます'
    monkeypatch.setattr(wide,'ACCESS_NOTICE_SHA256',frozenset({hashlib.sha256(notice.encode()).hexdigest()}))
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=os.environ.get('TATEMONO_CHROMIUM_EXECUTABLE'))
        page=browser.new_page()
        try:
            page.set_content('<p>'+notice+'</p>')
            state=wide.access_unavailable(page)
            assert state.code=='access_request_required' and state.evidence['request_sent'] is False
            page.set_content('<nav><a>'+notice+'</a></nav>')
            assert wide.access_unavailable(page) is None
            page.set_content('<p>'+notice+'</p><form></form>')
            assert wide.access_unavailable(page) is None
            page.set_content('<p>公開と許可申請の文字を含む未知の障害</p>')
            assert wide.access_unavailable(page) is None
        finally:browser.close()


def test_zero_and_blank_routes_are_excluded_and_counts_not_fixed():
    body='<meta charset="utf-8"><table><tr><th>会社名</th><th>物件数</th></tr>'
    for number,value in [(8,'1'),(26,'2'),(11,'0'),(12,''),(13,'1,234')]:
        body+=f'<tr><td>架空会社</td><td data-href="/company/lists/{number}">{value}</td></tr>'
    body+='</table>'
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=os.environ.get('TATEMONO_CHROMIUM_EXECUTABLE'))
        page=browser.new_page()
        page.route(ORIGIN+'/**',lambda r:r.fulfill(status=200,content_type='text/html; charset=utf-8',body=body))
        try:
            page.goto(ORIGIN+'/company')
            catalog=company_catalog(page)
            assert [x['company_id'] for x in catalog]==['8','13','26']
            assert catalog.counts['positive_count']==3
            assert {x['status'] for x in catalog.excluded}=={'zero_count','blank_count'}
        finally:browser.close()


def test_observed_company_header_with_line_breaks_and_full_width_space():
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=os.environ.get('TATEMONO_CHROMIUM_EXECUTABLE'))
        page=browser.new_page()
        try:
            page.set_content('<a>物件検索(ALL)</a><div id="search_list_header"><div class="f_left">　物件検索\n　（架空会社　管理部）</div></div>')
            assert observed_company_label(page)=='架空会社 管理部'
        finally:browser.close()
