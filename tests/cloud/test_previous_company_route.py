import pytest

from tatemono_map.cloud.collector import CollectionError, ORIGIN
from tatemono_map.cloud.wide import CompanyCatalog,complete_catalog


def test_missing_index_link_uses_only_a_previous_verified_route_for_live_recheck():
    current=CompanyCatalog([{'company_id':'8','search_url':ORIGIN+'/company/lists/8'}],[],{})
    old=[{'company_id':'8','search_url':ORIGIN+'/company/lists/8'},
        {'company_id':'26','search_url':ORIGIN+'/company/lists/26'}]
    result=complete_catalog(current,old)
    assert [x['company_id'] for x in result]==['8','26']
    assert result.counts['prior_route_checks']==1
    # A previous successful fetch must never bypass an explicit new access wall.
    current.excluded=[{'company_id':'26','status':'request_required'}]
    with pytest.raises(CollectionError,match='now_requires_access_request'):
        complete_catalog(current,old)


def test_previous_routes_never_accept_guessed_or_foreign_targets():
    current=CompanyCatalog([],[],{})
    for url in ('https://example.org/company/lists/26',ORIGIN+'/company/lists/8',ORIGIN+'/company/request/26'):
        with pytest.raises(CollectionError,match='catalog_invalid'):
            complete_catalog(current,[{'company_id':'26','search_url':url}])
