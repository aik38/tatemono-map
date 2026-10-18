from types import SimpleNamespace

import pytest

from tatemono_map.cloud import wide
from tatemono_map.cloud.collector import CollectionError, ORIGIN


class Page:
    def __init__(self, destinations, password_fields=1):
        self.destinations = iter(destinations)
        self.password_fields = password_fields

    def goto(self, url, **kwargs):
        self.url, status = next(self.destinations)
        return SimpleNamespace(status=status)

    def locator(self, selector):
        assert selector == 'input[type="password"]:visible'
        return SimpleNamespace(count=lambda: self.password_fields)


def test_expired_session_resumes_same_company_and_renews_only_once(monkeypatch):
    target = ORIGIN + '/company/lists/69'
    page = Page([(ORIGIN + '/', 200), (target, 200), (ORIGIN + '/', 200)])
    logins = []
    monkeypatch.setattr(wide.c, 'login_to_company_index', lambda p, credentials: logins.append(p))
    session = {}
    wide.navigate_company(page, target, {}, session)
    assert page.url == target and len(logins) == 1
    with pytest.raises(CollectionError, match='company_discovered_route_navigation_failed'):
        wide.navigate_company(page, target, {}, session)
    assert len(logins) == 1


@pytest.mark.parametrize('destination,password_fields', [
    ('https://elsewhere.invalid/', 1), (ORIGIN + '/', 0), (ORIGIN + '/', 2),
    (ORIGIN + '/company', 1),
])
def test_unknown_redirect_or_nonunique_login_never_receives_credentials(monkeypatch, destination, password_fields):
    page = Page([(destination, 200)], password_fields)
    def forbidden(*args):
        pytest.fail('credentials must not be entered here')
    monkeypatch.setattr(wide.c, 'login_to_company_index', forbidden)
    with pytest.raises(CollectionError, match='company_discovered_route_navigation_failed'):
        wide.navigate_company(page, ORIGIN + '/company/lists/69', {}, {})


def test_failed_renewal_consumes_the_batch_budget(monkeypatch):
    page = Page([(ORIGIN + '/', 200)])
    def failed(*args):
        raise CollectionError('ulucks_login_page_unavailable')
    monkeypatch.setattr(wide.c, 'login_to_company_index', failed)
    session = {}
    with pytest.raises(CollectionError, match='ulucks_login_page_unavailable'):
        wide.navigate_company(page, ORIGIN + '/company/lists/69', {}, session)
    assert session['renewal_attempted'] is True
