"""Read actual index route shapes using the unchanged Cloud Run runtime."""
import json
import os
import re
import subprocess
from datetime import datetime, timezone, timedelta
import time

REMOTE=r'''
import os,json,re,tempfile
from pathlib import Path
from urllib.parse import urlsplit,urljoin,parse_qs
from playwright.sync_api import sync_playwright
from tatemono_map.cloud import collector as c
from tatemono_map.cloud.run import secret_json,new_run_id
from tatemono_map.cloud.storage import GCSStore
store=GCSStore(os.environ['TATEMONO_BUCKET']);before=store.read_head();run=new_run_id()
credentials=secret_json(os.environ['ULUCKS_LOGIN_SECRET'])
report=[];shapes={}
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,executable_path=os.environ.get('TATEMONO_CHROMIUM_EXECUTABLE'))
    page=browser.new_page(locale='ja-JP')
    try:
        page.goto(c.ORIGIN+'/',wait_until='domcontentloaded')
        c.only(page.locator('input:not([type]):visible, input[type="text"]:visible, input[type="email"]:visible'),'login_username').fill(credentials['username'])
        c.only(page.locator('input[type="password"]:visible'),'login_password').fill(credentials['password'])
        login=page.get_by_role('button',name=re.compile('^ログイン$'))
        if login.count()==0:login=page.get_by_role('link',name=re.compile('^ログイン$'))
        c.only(login,'login_action').click()
        c.only(page.get_by_role('link',name='会社検索',exact=True),'company_search').click()
        row=c.only(page.get_by_role('row').filter(has_text=re.compile(re.escape(c.COMPANY_LABEL))),'company_row')
        table=row.locator('xpath=ancestor::table[1]')
        for cell in page.locator('td[data-href]').all():
            raw=cell.get_attribute('data-href') or ''
            url=urljoin(page.url,raw);u=urlsplit(url)
            same=u.scheme=='https' and u.netloc==urlsplit(c.ORIGIN).netloc
            match=bool(re.fullmatch(r'/company/lists/[0-9]+/?',u.path))
            in_table=table.evaluate('(el,other)=>el.contains(other)',cell.element_handle())
            kind='company_route' if same and match and not u.query and not u.fragment else 'other'
            shape={'same_origin':same,'company_path':match,'path_shape':re.sub('[0-9]+','#',u.path)[:150],
                'query_keys':list(parse_qs(u.query))[:12],'fragment_present':bool(u.fragment),'in_company_table':in_table,
                'numeric_count':bool(re.fullmatch('[0-9,]+',c.normal(cell.inner_text())))}
            token=json.dumps(shape,sort_keys=True);shapes[token]=shapes.get(token,0)+1
            report.append({'url':url,'kind':kind,'in_company_table':in_table})
        print('COMPANY_ROUTE_SHAPES='+json.dumps([{'count':n,**json.loads(s)} for s,n in shapes.items()],ensure_ascii=False),flush=True)
        print('COMPANY_ROUTE_ROWS='+json.dumps({'all_route_cells':len(report),'company_table_rows':table.get_by_role('row').count()}),flush=True)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'routes.json';p.write_text(json.dumps(report,ensure_ascii=False));store.upload(p,'private-runs/'+run+'/company-routes.json')
        print('COMPANY_ROUTE_SAVED='+json.dumps({'run_id':run,'head_unchanged':store.read_head()==before}),flush=True)
    except Exception as exc:
        print('COMPANY_ROUTE_ERROR='+json.dumps({'class':type(exc).__name__,'code':str(exc) if isinstance(exc,c.CollectionError) else 'route_observation_failed'}),flush=True)
        raise SystemExit(1)
    finally:
        try:
            logout=page.get_by_role('link',name='ログアウト',exact=True).or_(page.get_by_role('button',name='ログアウト',exact=True))
            if logout.count()==1:logout.click(timeout=5000)
        except Exception:pass
        browser.close()
'''


def main():
    base=['gcloud','--project',os.environ['GCP_PROJECT_ID'],'--quiet']
    def gc(args):
        p=subprocess.run(base+args,text=True,capture_output=True,timeout=600)
        if p.returncode:
            print(json.dumps({'command_failed':args[:3],'error_classes':sorted(set(re.findall(r'\b(?:PERMISSION_DENIED|INVALID_ARGUMENT|NOT_FOUND|UNAUTHENTICATED|DEADLINE_EXCEEDED)\b',p.stderr)))}))
            return None
        return p.stdout
    region=os.environ['GCP_REGION'];job=os.environ['GCP_JOB']
    logs_only=os.environ.get('ROUTES_READ_LOGS_ONLY')=='true'
    rows='[]' if logs_only else gc(['run','jobs','executions','list','--job',job,'--region',region,'--format=json'])
    if rows is None or any(not x.get('status',{}).get('completionTime') for x in json.loads(rows)):
        raise SystemExit('active_or_unreadable_executions_refusing_observation')
    start=(datetime.now(timezone.utc)-timedelta(minutes=15) if logs_only else datetime.now(timezone.utc)).isoformat()
    assert '~' not in REMOTE
    outcome='read_only' if logs_only else gc(['run','jobs','execute',job,'--region',region,'--args=^~^-c~'+REMOTE,'--wait','--format=json'])
    query='resource.type="cloud_run_job" AND resource.labels.job_name="'+job+'" AND timestamp>="'+start+'"'
    raw=gc(['logging','read',query,'--limit=200','--order=asc','--format=json'])
    if raw:
        for entry in json.loads(raw):
            value=entry.get('textPayload') or (entry.get('jsonPayload') or {}).get('message','')
            if isinstance(value,str) and value.startswith(('COMPANY_ROUTE_SHAPES=','COMPANY_ROUTE_ROWS=','COMPANY_ROUTE_SAVED=','COMPANY_ROUTE_ERROR=')):
                print(value)
            elif isinstance(value,str) and value.startswith('ULUCKS_WIDE_SAFE='):
                record=json.loads(value.split('=',1)[1])
                if record.get('stage') in ('catalog','search'):
                    keys=('company_count','pages','listed_rows','zero_without_route','other_without_route','request_required','collectable_companies','result_count','child_area_count','scope_verified')
                    safe={k:record[k] for k in keys if type(record.get(k)) in (int,bool)}
                    print('CURRENT_COLLECTION_PROGRESS='+json.dumps({'timestamp':entry.get('timestamp'),'stage':record['stage'],**safe},ensure_ascii=False))
            elif isinstance(value,str) and value.startswith('ULUCKS_UI_SAFE='):
                record=json.loads(value.split('=',1)[1])
                if record.get('stage') in ('print_started','print_exception','company_title_verified'):
                    print('CURRENT_COLLECTION_PROGRESS='+json.dumps({'timestamp':entry.get('timestamp'),'stage':record['stage']}))
            payload=entry.get('jsonPayload') or {}
            if payload.get('status') in ('failed','committed') and isinstance(payload.get('code',''),str) and re.fullmatch('[a-z][a-z0-9_]{0,100}',payload.get('code','')):
                print('CURRENT_COLLECTION_RESULT='+json.dumps({'timestamp':entry.get('timestamp'),'status':payload['status'],'code':payload['code']}))
    if outcome is None:raise SystemExit('route_observation_failed')

if __name__=='__main__':main()
