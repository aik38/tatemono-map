"""Exercise delayed company panels and the site's blank-label box handler."""
from contextlib import contextmanager
from types import SimpleNamespace as N
import json
import pytest
from tatemono_map.cloud import realpro as r
from tatemono_map.cloud.collector import CollectionError


class Panel:
    def __init__(self, page, selector): self.p, self.s = page, selector
    def count(self): return 1
    def inner_text(self):
        if self.s.startswith('.company_box'): return self.p.label
        if self.s == '#select_city': return self.p.area_text
        return '株式会社X'
    def input_value(self): return '37100'
    def locator(self, selector):
        assert selector == '..'
        return N(click=lambda **kw: self.p.clicked.append('company_box'))
    def evaluate(self, source):
        self.p.reads += 1
        # Company ID alone may be current while title/cities are still stale.
        stale = self.p.reads < 3
        return dict(id='37100', title='前会社' if stale else '株式会社X',
                    areaTitle='前会社' if stale else '株式会社X',
                    cities=[dict(value='40214' if stale else '40131', label='豊前市' if stale else '福岡市東区')],
                    towns=['40214001'] if stale else ['40131007'])
    def set_checked(self, value):
        assert self.p.reads >= 3, 'stale area was used'
        self.p.selected.append((self.s, value))
    def evaluate_all(self, source):
        return ['40131007'] if 'town_code' in self.s else ['40131']


class Page:
    def __init__(self, raw=None):
        self.label, self.reads, self.clicked, self.selected, self.area_text = '', 0, [], [], ''
        self.raw = raw or json.dumps(dict(company_name='株式会社X', pref=[dict(city=[
            dict(city_code='40131', city_name='福岡市東区', town=[dict(town_code='40131007')])])]))
    def locator(self, selector): return Panel(self, selector)
    def wait_for_timeout(self, ms): pass
    @contextmanager
    def expect_response(self, predicate, **kw):
        good=N(url=r.ORIGIN+'/ajax/get_list_area.php?id=37100',request=N(method='GET'))
        wrong=N(url=r.ORIGIN+'/ajax/get_list_area.php?id=49945',request=N(method='GET'))
        assert predicate(good) and not predicate(wrong)
        yield N(value=N(status=200, text=lambda: self.raw))


def test_blank_label_waits_for_company_name_and_current_regions():
    page=Page()
    assert r.choose(page,'37100','') == [dict(value='40131',label='福岡市東区')]
    assert page.clicked == ['company_box'] and page.reads == 3 and page.selected


def test_no_properties_requires_matching_response_and_visible_empty_message():
    page=Page('false');page.area_text='公開中の物件がありません'
    with pytest.raises(CollectionError,match='^realpro_no_published_properties$'):
        r.choose(page,'37100','')
    assert not page.selected


def test_town_from_another_city_is_rejected():
    page=Page(json.dumps(dict(company_name='株式会社X',pref=[dict(city=[
        dict(city_code='40131',city_name='福岡市東区',town=[dict(town_code='40214001')])])])) )
    with pytest.raises(CollectionError,match='realpro_company_area_towns_invalid'):
        r.choose(page,'37100','')
    assert not page.selected


def test_malformed_id_is_rejected_without_selecting_company():
    page=Page()
    with pytest.raises(CollectionError,match='realpro_company_id_invalid'):
        r.choose(page,'37100;other','')
    assert not page.clicked


def execution_fixture(monkeypatch):
    from contextlib import nullcontext
    from tatemono_map.cloud import realpro_weekly as w
    import playwright.sync_api
    page=object()
    browser=N(new_context=lambda **kw:N(new_page=lambda:page,storage_state=lambda:{}),close=lambda:None)
    monkeypatch.setattr(playwright.sync_api,'sync_playwright',lambda:nullcontext(N(chromium=N(launch=lambda **kw:browser))))
    monkeypatch.setenv('REALPRO_LOGIN_SECRET','test')
    monkeypatch.setattr(w,'secret_json',lambda *a:{})
    monkeypatch.setattr(w,'login',lambda p,creds:p)
    monkeypatch.setattr(w,'discover',lambda p:[dict(company_id='37100',company_label='',availability='available')])
    monkeypatch.setattr(w,'new_run_id',lambda:'20261026T160000Z-111111111111')
    return w


def test_time_budget_saves_deferred_manifest_without_starting_company(monkeypatch,tmp_path):
    w=execution_fixture(monkeypatch)
    monkeypatch.setattr(w,'read_json',lambda *a:None)
    monkeypatch.setattr(w.time,'monotonic',lambda:0)
    saved=[]
    monkeypatch.setattr(w,'save_json',lambda store,work,name,data:saved.append((name,data)) or {})
    def forbidden(*a,**kw):raise AssertionError('company should be deferred')
    monkeypatch.setattr(w,'isolated_company',forbidden)
    result=w.execute(object(),tmp_path,cycle='new-cycle',source_commit='a'*40,commit=True,deadline=100)
    assert result['status']=='continuation_required' and result['deferred_companies']==1
    assert any('acquisition-manifest.json' in name for name,data in saved)
    assert not any(name.endswith('/integration.json') for name,data in saved)


def test_verified_zero_is_reused_without_pdf_or_deletion(monkeypatch,tmp_path):
    w=execution_fixture(monkeypatch)
    empty=dict(company_id='37100',status='verified_empty')
    monkeypatch.setattr(w,'read_json',lambda store,name:dict(empty) if name.endswith('/result.json') else None)
    monkeypatch.setattr(w,'save_json',lambda *a:{})
    def forbidden(*a,**kw):raise AssertionError('verified zero should not reacquire or integrate')
    monkeypatch.setattr(w,'isolated_company',forbidden)
    monkeypatch.setattr(w,'integrate',forbidden)
    head={'run_id':'existing'}
    result=w.execute(N(read_head=lambda:(head,7)),tmp_path,cycle='same-cycle',source_commit='a'*40,commit=True)
    assert result['zero_companies']==1 and result['head']==head and result['status']=='no_new_content'


def test_apaman_pdf_width_equivalence_is_bound_to_verified_id_and_full_names():
    from tatemono_map.cloud.realpro_weekly import pdf_company_title_matches as match
    assert match('37100','APAMAN 株式会社','ＡＰＡＭＡＮ株式会社')
    assert not match('49945','APAMAN 株式会社','ＡＰＡＭＡＮ株式会社')
    assert not match('37100','APAMAN株式会社 他営業所','ＡＰＡＭＡＮ株式会社')
    assert not match('37100','APAMAN株式会社','ＡＰＡＭＡＮ株式会社 他営業所')
    assert not match('37100','apaman株式会社','ＡＰＡＭＡＮ株式会社')
    assert match('20322','株式会社X(支店)','株式会社X（支店）')
