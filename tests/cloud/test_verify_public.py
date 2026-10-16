import io

import pytest
from tatemono_map.cloud import verify_public as verify


def test_production_detail_checks_real_displayed_rent_and_vacancy(monkeypatch):
    row={'id':'b1','name':'架空テスト','detail_filename':'架空テスト-b1.html'}
    marker={'run_id':'run','proof':[{'building_key':'b1','vacancy_count':2,'rent_yen_min':50000,'rent_yen_max':55000}]}
    class Response(io.BytesIO):
        status=200
        def geturl(self):return verify.SITE+'/b/example.html'
    body='<h1>架空テスト</h1><dt>空室</dt><dd>2件</dd><dt>賃料</dt><dd>50,000円〜55,000円</dd>'
    monkeypatch.setattr(verify,'urlopen',lambda *_a,**_k:Response(body.encode()))
    assert len(verify.verify_detail_pages(marker,[row]))==1
    body=body.replace('55,000','99,000')
    with pytest.raises(ValueError,match='rental_terms_mismatch'):
        verify.verify_detail_pages(marker,[row])
