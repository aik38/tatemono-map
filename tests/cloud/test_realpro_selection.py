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
