import json
import sqlite3
from contextlib import nullcontext
from types import SimpleNamespace as N
import pytest
from tatemono_map.cloud import realpro_weekly as w

@pytest.mark.parametrize('errors,expected,status', [
    ([],1,'pdf_verified'),
    (['building_name_noise_rows=1'],1,'pdf_verified'),
    (['building_name_noise_rows=1'],2,'failed'),
])
def test_acquisition_and_parser_quality_are_separate(monkeypatch,tmp_path,errors,expected,status):
    import playwright.sync_api
    from tatemono_map.cloud import realpro_batch
    hashed='a'*64
    receipt=dict(pdf={'sha256':hashed},company_title='株式会社X',regions=[],evidence={'expected_rows':expected})
    item=dict(metadata={'sha256':hashed,'company':'株式会社X'},rows=[{}],errors=errors)
    monkeypatch.setattr(w,'read_json',lambda store,name:receipt if name.endswith('acquisition.json') else item if name.endswith('parsed.json') else None)
    class Store:
        def __init__(self,*a):pass
        def download(self,ref,path):path.write_bytes(b'pdf')
        def upload_verified(self,path,name):return {'object':name}
    monkeypatch.setenv('TATEMONO_BUCKET','test');monkeypatch.setattr(w,'GCSStore',Store)
    monkeypatch.setattr(w,'save_json',lambda *a:{})
    def forbidden(*a,**kw):raise AssertionError('saved PDF must not be reacquired')
    monkeypatch.setattr(w,'discover',forbidden);monkeypatch.setattr(w,'choose',forbidden);monkeypatch.setattr(w,'acquire',forbidden)
    page=object()
    browser=N(new_context=lambda **kw:N(new_page=lambda:page),close=lambda:None)
    monkeypatch.setattr(playwright.sync_api,'sync_playwright',lambda:nullcontext(N(chromium=N(launch=lambda **kw:browser))))
    monkeypatch.setattr(realpro_batch,'parse_pdf',lambda *a:json.loads(json.dumps(item)))
    result=w.company_worker(dict(work=str(tmp_path),company={'company_id':'15649'},prefix='cycle',run='run',session={}))
    assert result['status']==status and result['reused_acquisition']
    if status=='pdf_verified':
        verified=json.loads((tmp_path/'verified-item.json').read_text())
        assert verified['errors']==errors
        assert result['analysis_status']==('quarantined_pdf' if errors else 'verified')
    else:
        assert result['failure_code']=='realpro_pdf_source_accounting_failed'
        assert not (tmp_path/'verified-item.json').exists()

def test_existing_importer_quarantines_all_uncertain_pdf_rows(master,tmp_path):
    from tests.cloud.test_realpro_batch import initialize,item
    from tatemono_map.cloud.realpro_batch import update_batch
    baseline=initialize(master,tmp_path)
    data=item([{},dict(room='102')]);data['errors']=['building_name_noise_rows=1']
    report=update_batch(master,[data],tmp_path,'quarantine',baseline)
    assert report['attached_rows']==0 and report['row_counts']=={'anomaly':2}
    assert report['counts_before']==report['counts_after']
    assert report['company_results'][0]['parser_errors']==data['errors']
    assert report['other_snapshots_preserved'] and report['ulucks_preserved']

@pytest.mark.parametrize('already_recorded',[False,True])
def test_new_private_quarantine_is_committed_once_without_adoption(monkeypatch,tmp_path,already_recorded):
    from tatemono_map.cloud import realpro_batch
    with sqlite3.connect(tmp_path/'master.sqlite3') as c:
        c.execute('CREATE TABLE realpro_pdf_inputs (sha256 TEXT)')
        if already_recorded:c.execute('INSERT INTO realpro_pdf_inputs VALUES (?)',('a'*64,))
    head={'run_id':'previous'}
    monkeypatch.setattr(realpro_batch,'backup_current',lambda *a:(head,7,{}))
    report=dict(attached_rows=0,parsed_rows=1,row_counts={'anomaly':1},counts_before={},counts_after={},public_counts={},pdf_count=1,pdf_pages=1,proof=[{'preservation':'verified'}])
    monkeypatch.setattr(realpro_batch,'update_batch',lambda *a,**kw:dict(report))
    monkeypatch.setattr(realpro_batch,'preserve_ulucks_catalog',lambda *a:None)
    monkeypatch.setattr(w,'save_json',lambda *a:{})
    commits=[]
    monkeypatch.setattr(w,'commit_release',lambda *a:commits.append(a) or {'run_id':'new'})
    store=N(collection_lease=lambda run:nullcontext())
    result=w.integrate(store,[dict(metadata={'sha256':'a'*64},errors=['quality'])],tmp_path,'new','b'*40,{},0)
    assert bool(commits)==(not already_recorded)
    assert result['status']==('no_new_content' if already_recorded else 'committed')
