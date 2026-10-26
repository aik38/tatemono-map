import os
import signal
import sys
import time
import json
import pytest
from tatemono_map.cloud import realpro_weekly as w
from tatemono_map.cloud.collector import CollectionError

def test_brackets_only():
    assert w.company_title('株式会社学生情報センター（ナジック）福岡天神店') == w.company_title('株式会社学生情報センター(ナジック)福岡天神店')
    assert w.company_title('株式会社エイブル 九州広島管理事業部（北九州募集）') == w.company_title('株式会社エイブル 九州広島管理事業部(北九州募集)')
    assert w.company_title('株式会社Ａ（支店）') != w.company_title('株式会社A(支店)')
    assert w.company_title('株式会社X(支店)') != w.company_title('株式会社X')

def test_wedged_process_and_children_are_killed(tmp_path):
    pidfile = tmp_path/'pid'
    source = '''import subprocess,signal,time,sys
signal.signal(signal.SIGTERM, signal.SIG_IGN)
p=subprocess.Popen([sys.executable, '-c', 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(600)'])
open(sys.argv[1],'w').write(str(p.pid))
time.sleep(600)
'''
    started = time.monotonic()
    with pytest.raises(CollectionError, match='realpro_company_process_timeout'):
        w.run_bounded([sys.executable, '-c', source, str(pidfile)], .5)
    assert time.monotonic()-started < 8
    pid = int(pidfile.read_text())
    stat = __import__('pathlib').Path(f'/proc/{pid}/stat')
    assert not stat.exists() or stat.read_text().split()[2] == 'Z'

def test_normal_process():
    assert w.run_bounded([sys.executable, '-c', 'pass'], 5) == 0

def test_timeout_retries_only_company_and_records_failure(monkeypatch,tmp_path):
    calls=[]
    def fail(command,timeout):
        calls.append(command)
        raise CollectionError('realpro_company_process_timeout')
    monkeypatch.setattr(w,'run_bounded',fail)
    config=dict(work=str(tmp_path),company={'company_id':'49945'},session={})
    result=w.isolated_company(config,timeout=.1)
    assert len(calls)==2 and result['status']=='failed' and result['company_id']=='49945'

def test_transient_failure_recovers(monkeypatch,tmp_path):
    calls=[]
    def run(command,timeout):
        calls.append(command)
        result={'status':'failed','failure_code':'TimeoutError'} if len(calls)==1 else {'status':'pdf_verified','reused_acquisition':True}
        (tmp_path/'worker-result.json').write_text(json.dumps(result))
        return 0
    monkeypatch.setattr(w,'run_bounded',run)
    result=w.isolated_company(dict(work=str(tmp_path),company={},session={}))
    assert result['status']=='pdf_verified' and result['attempts']==2
    assert result['attempt_failures']==['TimeoutError']

def test_deterministic_error_is_not_retried(monkeypatch,tmp_path):
    calls=[]
    def run(command,timeout):
        calls.append(command)
        (tmp_path/'worker-result.json').write_text(json.dumps({'status':'failed','failure_code':'realpro_pdf_company_title_mismatch'}))
        return 0
    monkeypatch.setattr(w,'run_bounded',run)
    assert w.isolated_company(dict(work=str(tmp_path),company={},session={}))['status']=='failed'
    assert len(calls)==1

class Blob:
    generation=7
    def __init__(self,old): self.old=old; self.writes=[]; self.deletes=[]
    def upload_from_string(self,payload,**kw):
        from google.api_core.exceptions import PreconditionFailed
        self.writes.append(kw['if_generation_match'])
        if kw['if_generation_match']==0: raise PreconditionFailed('exists')
        self.generation=8
    def reload(self): pass
    def download_as_bytes(self,**kw): assert kw['if_generation_match']==7; return json.dumps(self.old).encode()
    def delete(self,**kw): self.deletes.append(kw['if_generation_match'])

@pytest.mark.parametrize('old_attempt,allowed', [('0',True),('1',False),('2',False)])
def test_managed_retry_reclaims_only_ended_attempt(monkeypatch,old_attempt,allowed):
    from types import SimpleNamespace
    monkeypatch.setenv('CLOUD_RUN_EXECUTION','tatemono-realpro-weekly-test')
    monkeypatch.setenv('CLOUD_RUN_TASK_INDEX','0')
    monkeypatch.setenv('CLOUD_RUN_TASK_ATTEMPT','1')
    blob=Blob(dict(execution='tatemono-realpro-weekly-test',task='0',attempt=old_attempt,expires_at=time.time()+99999))
    store=SimpleNamespace(bucket=SimpleNamespace(blob=lambda name:blob))
    if allowed:
        with w.acquisition_lease(store,'new'): pass
        assert blob.writes==[0,7] and blob.deletes==[8]
    else:
        with pytest.raises(CollectionError,match='already_running'):
            with w.acquisition_lease(store,'new'): pass
        assert blob.writes==[0] and blob.deletes==[]

@pytest.mark.parametrize('response,allowed', [({'completionTime':'2026-10-26T01:05:39Z'},True),({},False),(None,False)])
def test_other_execution_must_be_confirmed_terminal(monkeypatch,response,allowed):
    import google.auth
    import google.auth.transport.requests
    from types import SimpleNamespace as N
    monkeypatch.setenv('CLOUD_RUN_EXECUTION','tatemono-realpro-weekly-current')
    monkeypatch.setattr(google.auth,'default',lambda **kw:(object(),None))
    calls=[]
    class Session:
        def __init__(self,*a): pass
        def get(self,url,**kw):
            calls.append(url)
            return N(status_code=200 if response is not None else 403,json=lambda:response)
        def close(self): pass
    monkeypatch.setattr(google.auth.transport.requests,'AuthorizedSession',Session)
    blob=Blob(dict(execution='tatemono-realpro-weekly-old',expires_at=0))
    store=N(bucket=N(blob=lambda name:blob))
    if allowed:
        with w.acquisition_lease(store,'new'): pass
        assert blob.writes==[0,7]
    else:
        with pytest.raises(CollectionError,match='already_running'):
            with w.acquisition_lease(store,'new'): pass
        assert blob.writes==[0]
    assert calls[0].endswith('/tatemono-realpro-weekly-old')

def test_saved_pdf_bypasses_provider_and_reuses_cache(monkeypatch,tmp_path):
    from types import SimpleNamespace as N
    from contextlib import nullcontext
    import playwright.sync_api
    from tatemono_map.cloud import realpro_batch
    hashed='a'*64
    receipt=dict(pdf={'sha256':hashed},company_title='株式会社X（支店）',regions=[],evidence={'expected_rows':1})
    item=dict(metadata={'sha256':hashed,'company':'株式会社X(支店)'},rows=[{}],errors=[])
    saved=[]
    monkeypatch.setattr(w,'read_json',lambda store,name:receipt if name.endswith('acquisition.json') else item if name.endswith('parsed.json') else None)
    class Store:
        def __init__(self,*a):pass
        def download(self,ref,path):path.write_bytes(b'pdf')
        def upload_verified(self,path,name):return {'object':name}
    monkeypatch.setenv('TATEMONO_BUCKET','test')
    monkeypatch.setattr(w,'GCSStore',Store)
    monkeypatch.setattr(w,'save_json',lambda store,work,name,value:saved.append(name))
    def forbidden(*a,**kw):raise AssertionError('provider must not be contacted')
    monkeypatch.setattr(w,'discover',forbidden);monkeypatch.setattr(w,'choose',forbidden);monkeypatch.setattr(w,'acquire',forbidden)
    page=N(locator=lambda s:N(is_visible=lambda:False))
    browser=N(new_context=lambda **kw:N(new_page=lambda:page),close=lambda:None)
    monkeypatch.setattr(playwright.sync_api,'sync_playwright',lambda:nullcontext(N(chromium=N(launch=lambda **kw:browser))))
    def parse(pdf,cache):
        assert json.loads((cache/(hashed+'.json')).read_text())==item
        return json.loads(json.dumps(item))
    monkeypatch.setattr(realpro_batch,'parse_pdf',parse)
    result=w.company_worker(dict(work=str(tmp_path),company={'company_id':'20322'},prefix='cycle',run='run',session={}))
    assert result['status']=='pdf_verified' and result['reused_acquisition']
    assert all(not name.endswith('result.json') for name in saved)
