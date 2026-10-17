"""Observe live Ulucks through the existing runtime without releasing data.

Uses one execution override, not a persistent Job/config/Secret change. Member
company details and control values stay in the existing private GCS bucket.
"""
import json
import os
import re
import subprocess
from datetime import datetime, timezone

REMOTE = r'''
import json, os, re, tempfile
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlsplit, urljoin
from tatemono_map.cloud import collector as c
from tatemono_map.cloud.run import secret_json, new_run_id
from tatemono_map.cloud.storage import GCSStore, validate_head

class ObservationComplete(c.CollectionError): pass

def main():
    store = GCSStore(os.environ['TATEMONO_BUCKET'])
    head, generation = store.read_head()
    validate_head(head)
    print('FULLAREA_HEAD='+json.dumps({'run_id':head['run_id'], 'master_sha256':head['master']['sha256'], 'public_sha256':head['public']['sha256'], 'counts':head['report'].get('counts_after'), 'public_counts':head['report'].get('public_counts')}),flush=True)
    config = json.loads(os.environ['ULUCKS_CONFIG_JSON']) if os.environ.get('ULUCKS_CONFIG_JSON') else secret_json(os.environ['ULUCKS_CONFIG_SECRET'])
    credentials = secret_json(os.environ['ULUCKS_LOGIN_SECRET'])
    report = {}
    original = c._observe_company_row
    def companies(page, row, root):
        report['company_row_links'] = row.locator('a').evaluate_all("els => els.map(el=>({tag:el.tagName,href:el.getAttribute('href'),onclick:el.getAttribute('onclick')}))")
        shapes=[]
        for x in report['company_row_links']:
            raw=(x.get('href') or '')+' '+(x.get('onclick') or '')
            shapes.append({'tag':x['tag'],'paths':re.findall(r'/company/lists/[0-9]+',raw),'functions':re.findall(r'([a-zA-Z_][a-zA-Z0-9_.]*)\s*\(',raw),'href_scheme':urlsplit(x.get('href') or '').scheme,'has_onclick':bool(x.get('onclick'))})
        print('FULLAREA_COMPANY_LINK_SHAPES='+json.dumps(shapes),flush=True)
        report['company_links'] = page.locator('a[href]').evaluate_all(''' + '"""' + r'''els => els.map(el => ({href:el.href, text:el.closest('tr')?.innerText || el.innerText})).filter(x => {const u=new URL(x.href);return u.origin==='https://kitakyushu.ulucks.jp' && /^\/company\/lists\/\d+\/?$/.test(u.pathname) && !u.search && !u.hash})''' + '"""' + r''')
        report['company_paging'] = page.locator('a[href]').evaluate_all(''' + '"""' + r'''els => els.filter(el=>/次|前|最後|最初|^[0-9]+$/.test((el.innerText||'').trim())).map(el=>({text:el.innerText,href:el.href})).filter(x=>{const u=new URL(x.href);return u.origin==='https://kitakyushu.ulucks.jp' && u.pathname.startsWith('/company')})''' + '"""' + r''')
        print('FULLAREA_COMPANY_COUNT='+str(len(set(x['href'] for x in report['company_links']))),flush=True)
        print('FULLAREA_COMPANY_PAGING_COUNT='+str(len(report['company_paging'])),flush=True)
        return original(page,row,root)
    def observe(page, root):
        form, area = c._search_form(page)
        report['controls'] = form.locator('input[type="checkbox"]').evaluate_all(''' + '"""' + r'''els => els.map(el=>({id:el.id,name:el.name,value:el.value,checked:el.checked,labels:Array.from(el.labels||[]).map(x=>x.innerText)}))''' + '"""' + r''')
        report['area_ancestors'] = area.evaluate(''' + '"""' + r'''el => {const rows=[];for(let p=el.parentElement,i=0;p&&i<7;p=p.parentElement,i++){rows.push({tag:p.tagName,classes:p.className,checkboxes:p.querySelectorAll('input[type=checkbox]').length,labels:Array.from(p.querySelectorAll('input[type=checkbox]')).flatMap(x=>Array.from(x.labels||[]).map(l=>l.innerText.trim()))});}return rows;}''' + '"""' + r''')
        print('FULLAREA_TARGET_LABELS='+json.dumps(next(x['labels'] for x in report['area_ancestors'] if x['checkboxes']==23),ensure_ascii=False),flush=True)
        safe=[]
        for row in report['area_ancestors']:
            safe.append({'tag':row['tag'],'checkboxes':row['checkboxes'],'geographic_labels':[x for x in row['labels'] if x in ('北九州','福岡市','福岡県その他') or re.fullmatch(r'[一-龥ぁ-んァ-ヶー]{1,15}(?:市|区|町|村)',x)]})
        print('FULLAREA_GEOGRAPHIC_STRUCTURE='+json.dumps(safe,ensure_ascii=False),flush=True)
        raise ObservationComplete()
    c._observe_company_row = companies
    c._search = observe
    run = new_run_id()
    with tempfile.TemporaryDirectory() as d:
        try:
            c.collect(config,credentials,Path(d)/'pdf')
        except ObservationComplete:
            pass
        target=Path(d)/'observation.json'
        target.write_text(json.dumps(report,ensure_ascii=False))
        ref=store.upload(target,'private-runs/'+run+'/fullarea-observation.json')
        print('FULLAREA_OBSERVATION='+json.dumps({'run_id':run,'saved':True,'head_unchanged':store.read_head()==(head,generation)}),flush=True)
try:
    main()
except Exception as exc:
    print('FULLAREA_ERROR='+json.dumps({'class':type(exc).__name__,'code':str(exc) if isinstance(exc,c.CollectionError) else 'observation_failed'}),flush=True)
    raise SystemExit(1)
'''


def main():
    env = os.environ
    base = ['gcloud', '--project', env['GCP_PROJECT_ID'], '--quiet']
    def gc(args):
        r = subprocess.run(base + args, capture_output=True, text=True, timeout=720)
        if r.returncode:
            codes = sorted(set(re.findall(r'\b(?:PERMISSION_DENIED|INVALID_ARGUMENT|NOT_FOUND|UNAUTHENTICATED|DEADLINE_EXCEEDED)\b', r.stderr)))
            print(json.dumps({'gcp_command_failed':args[:3], 'classes':codes,'exit_code':r.returncode}), flush=True)
            return None
        return r.stdout
    executions = gc(['run','jobs','executions','list','--job',env['GCP_JOB'],'--region',env['GCP_REGION'],'--format=json'])
    if executions is None or any(not x.get('status',{}).get('completionTime') for x in json.loads(executions)):
        raise SystemExit('active_or_unreadable_executions_refusing_observation')
    started = datetime.now(timezone.utc).isoformat()
    assert '~' not in REMOTE
    outcome = gc(['run','jobs','execute',env['GCP_JOB'],'--region',env['GCP_REGION'],'--args=^~^-c~'+REMOTE,'--wait','--format=json'])
    query = 'resource.type="cloud_run_job" AND resource.labels.job_name="'+env['GCP_JOB']+'" AND timestamp>="'+started+'"'
    logs = gc(['logging','read',query,'--limit=100','--order=asc','--format=json'])
    if logs:
        for entry in json.loads(logs):
            value = entry.get('textPayload','')
            if isinstance(value,str) and value.startswith(('FULLAREA_HEAD=','FULLAREA_COMPANY_COUNT=','FULLAREA_COMPANY_PAGING_COUNT=','FULLAREA_GEOGRAPHIC_STRUCTURE=','FULLAREA_OBSERVATION=','FULLAREA_ERROR=','FULLAREA_COMPANY_LINK_SHAPES=','FULLAREA_TARGET_LABELS=')):
                print(value,flush=True)
    if outcome is None:
        raise SystemExit('observation_execution_failed_no_job_or_master_changes')

if __name__ == '__main__':
    main()
