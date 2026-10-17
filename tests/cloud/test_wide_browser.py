import os
from urllib.parse import parse_qs

from playwright.sync_api import sync_playwright

from tatemono_map.cloud.wide import AREA_LABELS, search
from tatemono_map.cloud.wide import company_catalog
from tatemono_map.cloud.collector import ORIGIN, COMPANY_LABEL


def test_full_parent_group_excludes_every_other_selected_area(tmp_path):
    inputs=''.join(f'<label><input type="checkbox" name="area" value="{i}">{label}</label>' for i,label in enumerate(AREA_LABELS))
    body=f'''<meta charset="utf-8"><h2>物件検索（{COMPANY_LABEL}）</h2>
    <form method="post" action="{ORIGIN}/company/lists/8">
    <div><label><input type="checkbox" name="parent" value="north">北九州</label><div>{inputs}</div></div>
    <div><label><input type="checkbox" name="outside" value="fukuoka" checked>福岡市</label></div>
    <input type="submit" value="検索"></form>'''
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
    one='<meta charset="utf-8"><table><tr><td>架空甲社</td><td data-href="/company/lists/8">1</td></tr></table><a href="/company?page=2">2</a>'
    two='<meta charset="utf-8"><table><tr><td>架空乙社</td><td data-href="/company/lists/26">2</td></tr></table><a href="/company">前へ</a>'
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
            assert [x['company_id'] for x in company_catalog(page)]==['8','26']
            assert visited==[ORIGIN+'/company',ORIGIN+'/company?page=2']
        finally:
            browser.close()
