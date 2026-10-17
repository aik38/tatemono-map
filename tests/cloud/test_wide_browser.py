import os
from urllib.parse import parse_qs

from playwright.sync_api import sync_playwright

from tatemono_map.cloud.wide import AREA_LABELS, search
from tatemono_map.cloud.collector import ORIGIN, COMPANY_LABEL


def test_full_parent_group_excludes_every_other_selected_area(tmp_path):
    inputs=''.join(f'<label><input type="checkbox" name="area" value="{i}">{label}</label>' for i,label in enumerate(AREA_LABELS))
    body=f'''<h2>物件検索（{COMPANY_LABEL}）</h2>
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
                r.fulfill(status=200,content_type='text/html',body='検索結果1045件中')
            else:
                r.fulfill(status=200,content_type='text/html',body=body)
        page.route(ORIGIN+'/**',route)
        page.goto(ORIGIN+'/company/lists/8')
        try:
            assert search(page,tmp_path,{'company_label':COMPANY_LABEL})==1045
            assert sent[0]['area']==[str(i) for i in range(22)]
            assert 'outside' not in sent[0]
            assert sent[0]['parent']==['north']
        finally:
            browser.close()
