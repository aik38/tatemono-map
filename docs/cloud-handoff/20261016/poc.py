"""Isolated, read-only-source collection PoC. NO production DB, URL or GitHub writes.

All keyed URLs, cookies, Gmail message bodies, raw HTML and PDF content are private.
They are NEVER printed to logs. Reports redact source URLs by storing only domain/path.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urljoin, parse_qs

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.cloud import secretmanager, storage
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

PROJECT = os.environ.get('POC_PROJECT', 'tatemono-map')
BUCKET = os.environ.get('POC_BUCKET', 'tatemono-map-poc-523194690131')
REAL_SECRET = 'tm-poc-realpro-login'
GMAIL_SECRET = 'tm-poc-gmail-token'
SCOPE = ['https://www.googleapis.com/auth/gmail.readonly']
ROOT = Path(tempfile.mkdtemp(prefix='tm-poc-'))
RUN_ID = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
STORAGE = None
RESULT = {'run_id':RUN_ID,'mode':'','results':[], 'source_commit':'ef8ad263f47eb54bb53fd5903ba93b32b838bb38', 'production_db_write':False,'github_publish':False}

class Gate(Exception):
    """Controlled authentication/security/coverage stop; message must contain no secrets."""

def utcnow(): return datetime.now(timezone.utc).isoformat()
def store():
    global STORAGE
    if STORAGE is None: STORAGE = storage.Client(project=PROJECT)
    return STORAGE

def upload(path:Path,rel:str,ctype='application/octet-stream'):
    """Write a unique private object; no public ACLs, no mutating production objects."""
    key = f'poc-runs/{RUN_ID}/{rel}'
    store().bucket(BUCKET).blob(key).upload_from_filename(str(path), content_type=ctype, if_generation_match=0)
    return key

def write_json(o:object,rel:str):
    p=ROOT/rel; p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(o,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    return upload(p,rel,'application/json')

def secret(name):
    try:
        response=secretmanager.SecretManagerServiceClient().access_secret_version(request={'name':f'projects/{PROJECT}/secrets/{name}/versions/latest'})
        return json.loads(response.payload.data.decode('utf-8'))
    except Exception:
        raise Gate('Secret unavailable. Check that a version exists and PoC service account has accessor permission; values were not logged.') from None

def gmail():
    info=secret(GMAIL_SECRET)
    if not all(info.get(x) for x in ['refresh_token','client_id','client_secret','token_uri']):
        raise Gate('Gmail token missing required fields; repeat local OAuth bootstrap.')
    c=Credentials.from_authorized_user_info(info,SCOPE)
    if not c.valid:
        if not c.refresh_token: raise Gate('Gmail refresh token is absent')
        try: c.refresh(Request())
        except Exception: raise Gate('Gmail OAuth refresh failed (Testing token expiry, consent, or access revoked). Reauthorize locally; no secrets printed.') from None
    return build('gmail','v1',credentials=c,cache_discovery=False)

def decode_body(payload):
    out=[]
    def walk(p):
        mt=p.get('mimeType','')
        if mt in ('text/html','text/plain') and p.get('body',{}).get('data'):
            s=p['body']['data']; out.append(base64.urlsafe_b64decode(s+'='*(-len(s)%4)).decode('utf-8','replace'))
        for part in p.get('parts',[]): walk(part)
    walk(payload)
    return '\n'.join(out)

URL_RE=re.compile(r'https?://[^\s<>"\'）)]+',re.I)
def email_urls(body):
    # Handles both HTML hrefs and plaintext; no Gmail message content ever logged.
    text=html.unescape(body).replace('=\n','')
    urls=URL_RE.findall(text)
    return list(dict.fromkeys(v.rstrip('.,;，。') for v in urls))

def classify(url):
    try: u=urlsplit(html.unescape(url))
    except ValueError: return None
    
    try:
        if u.scheme!='https' or u.username or u.password or u.port not in (None,443): return None
    except ValueError: return None
    host=(u.hostname or '').lower()
    if host=='rent-b2b.n-create.jp' and u.path.rstrip('/')=='/ry-search' and parse_qs(u.query).get('auth_key'):
        return 'realpro-mail'
    if host=='kitakyushu.ulucks.jp' and u.path.startswith('/view/smartlink') and u.query:
        return 'ulucks'
    return None

def url_public_descriptor(url):
    u=urlsplit(url)
    return {'host':u.hostname,'path':u.path} # Never query, fragments or source URL in report.

def find_mail_sources(limit=100):
    service=gmail()
    # 21d only for proof of concept; no archive, modify, send, or trash calls.
    found=[]
    resp=service.users().messages().list(userId='me',q='newer_than:21d subject:空室一覧 -in:trash -in:spam',maxResults=limit).execute()
    for meta in resp.get('messages',[]):
        msg=service.users().messages().get(userId='me',id=meta['id'],format='full').execute()
        body=decode_body(msg.get('payload',{}))
        for link in email_urls(body):
            typ=classify(link)
            if typ:
                found.append({'type':typ,'url':link,'message_id':meta['id'],'received_epoch_ms':int(msg.get('internalDate',0))})
    # Same link from repeated MIME parts appears once, newer first.
    return sorted({(x['type'],x['url']):x for x in found}.values(),key=lambda v:v['received_epoch_ms'],reverse=True)

def check_pdf(data:bytes,prefix:str):
    from pypdf import PdfReader
    if not data.lstrip()[:5]==b'%PDF-': raise Gate('Downloaded data is not PDF (likely login/error HTML); not accepted.')
    p=ROOT/f'{prefix}.pdf';p.write_bytes(data)
    try:
        reader=PdfReader(str(p));pages=len(reader.pages)
        first=(reader.pages[0].extract_text() or '') if pages else ''
    except Exception: raise Gate('PDF magic detected but PDF parser failed; download rejected.') from None
    if not pages: raise Gate('PDF has zero pages; download rejected')
    return p, {'bytes':len(data),'pages':pages,'sha256':hashlib.sha256(data).hexdigest(),'first_page_text_chars':len(first)}

def parse_pdf(p:Path,kind:str,prefix:str):
    from tatemono_map.cli.pdf_batch_run import RealproParser,UlucksParser,qc_check,write_master_import_csv
    try:
        parser=RealproParser() if kind=='realpro' else UlucksParser()
        parsed=parser.parse(p);df=parsed.df
        qc=qc_check(df,kind) if len(df) else ['extracted_rows=0']
        out=ROOT/(prefix+'-master_import.csv'); write_master_import_csv(df,out)
        obj=upload(out,f'parsed/{out.name}','text/csv')
        columns={k:int(df[k].notna().sum()) if k in df.columns else 0 for k in ['building_name','address','room','rent_man','area_sqm','layout']}
        # full source fields only in PRIVATE CSV, no row-level PII in logs.
        return {'parser':parser.name,'rows':int(len(df)),'field_present_counts':columns,'qc_reasons':qc,'warnings':parsed.warnings,'private_csv_object':obj}
    except Exception:
        return {'parser':kind,'status':'failed','reason':'Existing parser failed; inspect private PDF and package version in isolated test. No production DB changed.'}

def page_login_stop(page):
    # Passive CAPTCHA badges/scripts are not active challenges.
    frames=page.locator('iframe:visible')
    for i in range(min(frames.count(),20)):
        src=(frames.nth(i).get_attribute('src') or '').lower()
        if '/recaptcha/api2/bframe' in src or ('hcaptcha' in src and 'challenge' in src):
            return 'captcha_challenge'
        if '/recaptcha/api2/anchor' in src and 'size=invisible' not in src:
            return 'captcha_checkbox'
    for status,needle in (
        ('terms_consent_required','リアプロBB+仲介ご利用に関する同意のお願い'),
        ('account_linkage_prompt','リアプロBBアカウントとの連携'),
        ('additional_auth_required','二段階認証'),
        ('additional_auth_required','ワンタイムパスワード'),
        ('additional_auth_required','認証コードを入力'),
        ('additional_auth_required','確認コードを入力'),
    ):
        nodes=page.get_by_text(needle,exact=False)
        if any(nodes.nth(i).is_visible() for i in range(min(nodes.count(),5))):
            return status
    return None

def screenshot_and_html(page,prefix:str):
    hp=ROOT/f'{prefix}.html';hp.write_text(page.content(),encoding='utf-8')
    img=ROOT/f'{prefix}.png';page.screenshot(path=str(img),full_page=False)
    return {'html':upload(hp,f'raw/{hp.name}','text/html'),'screenshot':upload(img,f'raw/{img.name}','image/png')}

def fetch_realpro_mail(src,number):
    url=src['url']; res={'type':'realpro-mail','index':number,'source':url_public_descriptor(url)}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        context=browser.new_context(accept_downloads=True,locale='ja-JP',viewport={'width':1366,'height':900})
        page=context.new_page()
        try:
            response=page.goto(url,wait_until='domcontentloaded',timeout=45000)
            page.wait_for_timeout(1700)
            res['http_status']=response.status if response else None
            res['private_evidence']=screenshot_and_html(page,f'realpro-mail-{number}')
            blocker=page_login_stop(page)
            if blocker: raise Gate('RealPro mail URL requires user interaction: '+blocker)
            if page.url.lower().endswith('.pdf'):
                # direct PDF could open inline; don't assume page HTML means pdf
                res['note']='PDF navigation detected; browser response must be separately captured'
            # Conservative: candidate PDF action only. Do not follow unsubscribe or off-host links.
            actions=[]
            for el in page.locator('a[href],button').all()[:120]:
                label=(el.inner_text(timeout=500) or '').strip()[:100]
                href=el.get_attribute('href') or ''
                if re.search(r'PDF|空室一覧出力|ダウンロード',label,re.I) or re.search(r'\.pdf(?:[?#]|$)',href,re.I):
                    absolute=urljoin(page.url,href) if href else ''
                    if absolute:
                        u=urlsplit(absolute)
                        if u.scheme!='https' or (u.hostname or '') not in ('rent-b2b.n-create.jp','www.realnetpro.com','realnetpro.com','login.n-create.jp'): continue
                    actions.append((el,label))
            res['pdf_action_candidates']=len(actions)
            if not actions:
                res['status']='html_only_pdf_button_not_verified'
                return res
            action,_=actions[0]
            try:
                with page.expect_download(timeout=20000) as pending: action.click(timeout=5000)
                dl=pending.value; filename=dl.suggested_filename
                data=Path(dl.path()).read_bytes()
                pdf,quality=check_pdf(data,f'realpro-mail-{number}')
                res['pdf']=quality
                res['private_pdf_object']=upload(pdf,f'raw/realpro-mail-{number}.pdf','application/pdf')
                res['parsed']=parse_pdf(pdf,'realpro',f'realpro-mail-{number}')
                res['status']='pdf_validated'
            except PwTimeout:
                res['status']='pdf_click_no_browser_download'
                res['private_after_click']=screenshot_and_html(page,f'realpro-mail-{number}-after')
            return res
        finally: browser.close()

def fetch_ulucks(src,number):
    from tatemono_map.ingest.smartlink_dom import extract_records
    from tatemono_map.ingest.ulucks_playwright import is_valid_smartlink_html,_extract_pagination_hrefs
    res={'type':'ulucks','index':number,'source':url_public_descriptor(src['url'])}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        context=browser.new_context(locale='ja-JP',viewport={'width':1366,'height':1000})
        page=context.new_page();url=src['url']
        try:
            response=page.goto(url,wait_until='domcontentloaded',timeout=45000)
            page.wait_for_timeout(2200)
            content=page.content()
            res['http_status']=response.status if response else None
            res['private_evidence']=screenshot_and_html(page,f'ulucks-{number}-1')
            ok,reason=is_valid_smartlink_html(content)
            res['html_validation']={'ok':ok,'reason':reason,'bytes':len(content.encode())}
            if not ok: res['status']='html_rejected';return res
            records=extract_records(page.url,content)
            pages=[(page.url,content)]
            # This PoC caps at 2 pages and verifies each link stays on the exact origin and path.
            for link in _extract_pagination_hrefs(page.url,content)[:1]:
                if not (urlsplit(link).hostname=='kitakyushu.ulucks.jp' and urlsplit(link).path.startswith('/view/smartlink')):continue
                page.goto(link,wait_until='domcontentloaded',timeout=45000);page.wait_for_timeout(1500)
                sub=page.content();pages.append((page.url,sub));records.extend(extract_records(page.url,sub))
                res['private_second_page']=screenshot_and_html(page,f'ulucks-{number}-2')
            res['pages']=len(pages);res['records']=len(records)
            # Private CSV uses existing ListingRecord fields and does not change any DB.
            import csv
            csvpath=ROOT/f'ulucks-{number}-parsed.csv'
            with csvpath.open('w',newline='',encoding='utf-8-sig') as f:
                writer=csv.DictWriter(f,fieldnames=['name','address','room_label','rent_yen','area_sqm','layout','maint_yen','updated_at','source_kind'])
                writer.writeheader()
                for r in records:writer.writerow({k:getattr(r,k,None) for k in writer.fieldnames})
            res['private_csv_object']=upload(csvpath,f'parsed/{csvpath.name}','text/csv')
            res['field_present_counts']={k:sum(bool(getattr(r,k,None)) for r in records) for k in ['name','address','room_label','rent_yen','area_sqm','layout']}
            res['status']='html_parsed' if records else 'html_valid_but_zero_records'
            return res
        finally:browser.close()

def do_site_probe():
    info=secret(REAL_SECRET)
    username=str(info.get('username') or '')
    password=str(info.get('password') or '')
    if not username or not password:raise Gate('RealPro login secret lacks username/password.')
    res={'type':'realpro-site','status':'not_tested'}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        context=browser.new_context(accept_downloads=True,locale='ja-JP',viewport={'width':1366,'height':900})
        page=context.new_page()
        try:
            response=page.goto('https://www.realnetpro.com/',wait_until='domcontentloaded',timeout=45000)
            page.wait_for_timeout(1200)
            res['login_screen_http_status']=response.status if response else None
            res['login_screen']=screenshot_and_html(page,'realpro-site-before')
            if page.locator('input[type="password"]').count()==0:
                res['status']='password_field_not_found';return res
            blocker=page_login_stop(page)
            if blocker: res['status']=blocker; return res
            pwd=page.locator('input[type="password"]').first
            fields=page.locator('input[type="text"],input[type="email"],input:not([type])')
            if fields.count()!=1:
                res['status']='login_identifier_field_ambiguous';res['identifier_field_count']=fields.count();return res
            fields.first.fill(username);pwd.fill(password)
            # Submit ONLY the nearest login form. Never click account creation etc.
            form=pwd.locator('xpath=ancestor::form[1]')
            if form.count()!=1:res['status']='login_form_ambiguous';return res
            # Select the actual visible login control, not just type=submit.
            def visible_login_controls(scope, include_links=False):
                selector='button,input[type="submit"],input[type="button"],input[type="image"],[role="button"]'
                if include_links: selector+=',a'
                controls=scope.locator(selector); found=[]
                for i in range(min(controls.count(),40)):
                    c=controls.nth(i)
                    if not c.is_visible() or not c.is_enabled(): continue
                    try: label=c.inner_text(timeout=1000)
                    except Exception: label=''
                    for attr in ('value','aria-label','title','alt'):
                        label+=' '+(c.get_attribute(attr) or '')
                    if 'ログイン' in [re.sub(r'\s+','',v) for v in label.split()]:
                        found.append(c)
                return found
            # Collect only status/method of same-origin responses; never URLs, bodies, headers or tokens.
            auth_events=[]
            def observed_response(response):
                try:
                    u=urlsplit(response.url)
                    req=response.request
                    if u.hostname in ('realnetpro.com','www.realnetpro.com') and (req.method.upper()=='POST' or req.resource_type=='document'):
                        auth_events.append({'method':req.method.upper() if req.method.upper() in ('GET','POST') else 'OTHER',
                                            'status':int(response.status),
                                            'kind':req.resource_type if req.resource_type in ('document','xhr','fetch') else 'OTHER'})
                except Exception:
                    pass
            page.on('response',observed_response)
            controls=visible_login_controls(form,True)
            if not controls: controls=visible_login_controls(page,False)
            if len(controls)>1:
                res['status']='login_control_ambiguous';return res
            try:
                if controls:
                    res['submit_method']='visible_login_button'
                    controls[0].click(timeout=15000)
                else:
                    res['submit_method']='password_enter'
                    pwd.press('Enter',timeout=10000)
            except PwTimeout:
                res['submit_action_timeout']=True
                # Inspect the resulting page even when a click wait times out.

            # A normal interactive login may finish after the click returns; allow time for it.
            page.wait_for_timeout(9000)
            first_password_visible=page.locator('input[type="password"]:visible').count()>0
            res['first_attempt_same_origin_responses']=auth_events[-12:]
            res['fallback_enter_attempted']=False
            # One standard keyboard fallback only if the click caused no observed same-origin
            # POST/navigation and the page is still at a normal login form. Never solve challenges.
            if first_password_visible and not auth_events and not page_login_stop(page):
                pwds=page.locator('input[type="password"]:visible')
                if pwds.count()==1:
                    res['fallback_enter_attempted']=True
                    try:
                        pwds.first.press('Enter',timeout=10000)
                    except PwTimeout:
                        res['fallback_enter_timeout']=True
                    page.wait_for_timeout(8000)
            res['post_submit_same_origin_responses']=auth_events[-12:]
            # Report only predefined flags based on rendered page text, never the text itself.
            try: visible=page.locator('body').inner_text(timeout=8000)
            except Exception: visible=''
            normalized=re.sub(r'\s+','',visible)
            res['visible_screen_signals']={
                'login_rejection':any(x in normalized for x in (
                    'ログインに失敗','ログインできません','IDまたはパスワード','パスワードが違います',
                    '認証に失敗','ログインIDが違','ログイン情報が正しく','入力内容をご確認')),
                'account_restricted':any(x in normalized for x in (
                    'アカウントがロック','ログイン制限','アカウントが停止')),
                'terms':('ご利用に関する同意のお願い' in normalized),
                'account_link':('リアプロBBアカウントとの連携' in normalized),
                'home':('サポートセンターからのお知らせ' in normalized),
            }
            res['after_login']=screenshot_and_html(page,'realpro-site-after')
            blocker=page_login_stop(page)
            if blocker=='account_linkage_prompt':
                later=page.get_by_text('あとで連携する',exact=False)
                choices=[later.nth(i) for i in range(min(later.count(),5)) if later.nth(i).is_visible()]
                if len(choices)==1:
                    choices[0].click(timeout=8000)
                    close=page.get_by_text('連携画面をとじる',exact=False)
                    for i in range(min(close.count(),5)):
                        if close.nth(i).is_visible():
                            close.nth(i).click(timeout=8000);break
                    page.wait_for_timeout(800)
                    blocker=page_login_stop(page)
            if blocker:res['status']=blocker;return res
            res['password_input_still_visible']=page.locator('input[type="password"]:visible').count()>0
            if res['password_input_still_visible']:
                signals=res.get('visible_screen_signals') or {}
                if signals.get('account_restricted'):res['status']='account_restricted_visible'
                elif signals.get('login_rejection'):res['status']='login_rejected_visible'
                elif res.get('post_submit_same_origin_responses'):res['status']='login_form_remains_after_server_response'
                else:res['status']='login_form_remains_without_observed_submit'
                return res
            u=urlsplit(page.url)
            home=u.hostname in ('realnetpro.com','www.realnetpro.com') and u.path=='/main.php'
            if home:
                page.goto('https://realnetpro.com/main.php?method=company_list',wait_until='domcontentloaded',timeout=35000)
                page.wait_for_timeout(1200)
                res['company_list_evidence']=screenshot_and_html(page,'realpro-site-company-list')
                blocker=page_login_stop(page)
                if blocker:res['status']=blocker;return res
                u=urlsplit(page.url)
                location_ok=(u.hostname in ('realnetpro.com','www.realnetpro.com')
                             and u.path=='/main.php' and 'method=company_list' in u.query)
                menu=page.get_by_text('管理会社一覧メニュー',exact=False)
                export=page.get_by_text('空室一覧出力',exact=False)
                menu_ok=any(menu.nth(i).is_visible() for i in range(min(menu.count(),5)))
                export_ok=any(export.nth(i).is_visible() for i in range(min(export.count(),5)))
                res['status']='login_home_confirmed' if location_ok and menu_ok and export_ok else 'login_not_confirmed'
            else:
                res['status']='login_not_confirmed'
            res['pdf_count']=0
            res['note']='Site login and company-list navigation only; PDF not yet downloaded.'
            return res
        finally:browser.close()

def run(mode):
    RESULT['mode']=mode
    if mode=='preflight':
        import tatemono_map.cli.pdf_batch_run as pdf
        import tatemono_map.ingest.smartlink_dom as dom
        RESULT['results'].append({'type':'preflight','status':'ok','browser':'playwright_chromium_image','existing_parser_imports':bool(pdf.RealproParser and pdf.UlucksParser and dom.extract_records),'bucket':BUCKET})
        return
    if mode=='site-probe':RESULT['results'].append(do_site_probe());return
    if mode not in ['mail-audit','realpro-mail','ulucks','all']:
        raise Gate('Unknown mode; accepted: preflight, mail-audit, realpro-mail, ulucks, site-probe, all')
    links=find_mail_sources()
    counts={k:sum(x['type']==k for x in links) for k in ['realpro-mail','ulucks']}
    RESULT['email']={'gmail_readonly':True,'source_link_counts':counts,'message_cap':100,'days':21}
    if mode=='mail-audit':return
    selected=[]
    if mode in ('realpro-mail','all'):selected.extend([x for x in links if x['type']=='realpro-mail'][:int(os.environ.get('REALPRO_POC_LIMIT','1'))])
    if mode in ('ulucks','all'):selected.extend([x for x in links if x['type']=='ulucks'][:int(os.environ.get('ULUCKS_POC_LIMIT','1'))])
    if not selected: raise Gate('No valid matching source links in last 21 days; inspect mail query/date without logging links.')
    for i,x in enumerate(selected,1):
        try:
            r=fetch_realpro_mail(x,i) if x['type']=='realpro-mail' else fetch_ulucks(x,i)
            RESULT['results'].append(r)
        except Gate as e:
            RESULT['results'].append({'type':x['type'],'index':i,'status':'blocked','reason':str(e)})
        except Exception:
            RESULT['results'].append({'type':x['type'],'index':i,'status':'failed','reason':'Collector exception; private evidence may contain more details. No keyed URLs or stack trace are logged.'})

def main():
    mode=sys.argv[1] if len(sys.argv)>1 else 'preflight'
    try:
        run(mode)
    except Gate as e:RESULT['error']=str(e)
    except Exception as exc:
        RESULT['error']='Unexpected error (redacted). Check configuration and permissions; secret values and URLs are never logged.'
        frames=[]
        tb=exc.__traceback__
        while tb is not None:
            code=tb.tb_frame.f_code
            if Path(code.co_filename).name=='poc.py':
                frames.append({
                    'function':code.co_name,
                    'line':int(tb.tb_lineno)
                })
            tb=tb.tb_next
        RESULT['diagnostic']={
            'exception_type':type(exc).__name__,
            'poc_frames':frames[-5:]
        }

    try:
        path=write_json(RESULT,'report.json')
        print('PRIVATE_REPORT_OBJECT='+path)
    except Exception:
        print('REPORT_SAVE_FAILED (check bucket permissions; no raw content printed)')
    print('POC_SUMMARY='+json.dumps({k:v for k,v in RESULT.items() if k in ('run_id','mode','email','error','results')},ensure_ascii=False))
    statuses=[r.get('status') for r in RESULT.get('results',[])]
    if 'error' in RESULT or any(s in ('blocked','failed') for s in statuses):return 2
    if mode=='site-probe' and statuses!=['login_home_confirmed']:return 2
    return 0

if __name__=='__main__':sys.exit(main())
