"""Resumable municipality/domain acquisition with immutable private originals."""
from __future__ import annotations
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
import requests
from selectolax.parser import HTMLParser
from tatemono_map.cloud.mansion_parser import BASE, VERSION, catalog, page_info, facts, more_request, parse_rows, text
from tatemono_map.cloud.mansion_geography import AREAS, MUNICIPALITIES, municipality


class Fetcher:
    def __init__(self, work, store=None, cycle='manual', delay=0.5):
        self.work=Path(work);self.work.mkdir(parents=True,exist_ok=True)
        self.store=store;self.cycle=cycle;self.delay=delay
        self.session=requests.Session()
        self.session.headers.update({'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36'})
        self.refs=[];self.next_at=0

    def get(self,url,*,params=None,referer=None):
        if urlsplit(url).netloc!='www.mansion-review.jp':raise ValueError('outside_mansion_source')
        if params:url+='?'+urlencode(params)
        key=hashlib.sha256(url.encode()).hexdigest()
        name=f'private-inputs/mansion-review/cycles/{self.cycle}/http/{key}'
        receipt=self.work/(key+'.json');path=self.work/(key+'.html')
        saved=None
        if self.store:
            from tatemono_map.cloud.realpro_weekly import read_json
            saved=read_json(self.store,name+'.json')
            if saved:
                if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=saved['ref']['sha256']:
                    self.store.download(saved['ref'],path)
        elif receipt.exists():saved=json.loads(receipt.read_text())
        if saved:
            if hashlib.sha256(path.read_bytes()).hexdigest()!=saved['sha256']:raise ValueError('mansion_cache_hash_mismatch')
            self.refs.append(saved);return path.read_text()
        last=None
        for attempt in range(3):
            time.sleep(max(0,self.next_at-time.monotonic()))
            try:
                r=self.session.get(url,headers={'Referer':referer or BASE},timeout=(20,90))
                self.next_at=time.monotonic()+self.delay
                if r.status_code!=200:raise ValueError('mansion_http_'+str(r.status_code))
                if urlsplit(r.url).netloc!='www.mansion-review.jp':raise ValueError('mansion_redirect_outside_source')
                r.encoding='utf-8';body=r.text
                if any(s in body.lower() for s in ('<title>just a moment','cf-chl-','<title>access denied')):raise ValueError('mansion_source_blocked')
                break
            except (requests.RequestException,ValueError) as e:
                last=e
                if attempt==2:raise ValueError('mansion_request_failed:'+type(e).__name__) from e
                time.sleep(2*(attempt+1))
        path.write_text(body,encoding='utf-8');sha=hashlib.sha256(path.read_bytes()).hexdigest()
        saved={'url':url,'sha256':sha,'acquired_at':datetime.now(timezone.utc).isoformat(),'http_status':200}
        if self.store:
            saved['ref']=self.store.upload_verified(path,f'private-inputs/mansion-review/originals/{sha}.html')
            receipt.write_text(json.dumps(saved,ensure_ascii=False));self.store.upload_verified(receipt,name+'.json')
        else:receipt.write_text(json.dumps(saved,ensure_ascii=False))
        self.refs.append(saved);return body


def collect_scope(fetcher, kind, name, entry):
    city_id=entry['city_id'];base=entry['url']
    rows=[];buildings=[];page_receipts=[];expected=None;max_page=1;page=1
    while page<=max_page:
        url=base if page==1 else base.replace('.html',f'_{page}.html')
        html=fetcher.get(url)
        tree,cards,info=page_info(html,kind,city_id,name)
        if expected is None:expected=info['total']
        if expected!=info['total']:raise ValueError('mansion_result_count_changed_during_crawl')
        max_page=max(max_page,info['max_page'])
        if max_page>1000:raise ValueError('mansion_pagination_limit')
        cla=re.search(r'window\._g_cla\s*=\s*["\']([^"\']+)',html)
        for card in cards:
            f=facts(card);f.update(city_id=city_id,municipality=name)
            if municipality(f['address'])!=name:raise ValueError('mansion_card_geography_mismatch')
            if f['building_url'] in buildings:raise ValueError('mansion_repeated_building_across_pages')
            buildings.append(f['building_url'])
            wraps=card.css('.js_rental_recommend' if kind=='chintai' else '.js_sales_recommend')
            for wrap in wraps:
                table=wrap.css_first('table.recommendTable')
                if table is None:continue
                initial=table.css('tbody.recommend_row tr')
                expanded=[]
                button=wrap.css_first('.js_rental_recommend_morebtn' if kind=='chintai' else '.js_sales_recommend_search_morebtn')
                target_count=len(initial)
                if button:
                    endpoint,params,target_count=more_request(wrap,button,kind,html)
                    more=fetcher.get(endpoint,params=params,referer=url)
                    # tbody fragments require a table context to avoid HTML5
                    # foster-parenting stripping their cells during parsing.
                    fragment=HTMLParser('<table>'+more+'</table>')
                    expanded=fragment.css('tbody.recommend_row tr')
                if len(initial)+len(expanded)!=target_count:raise ValueError('mansion_show_all_count_mismatch')
                parsed=parse_rows(table,initial+expanded,f,kind,url)
                if len(parsed)!=target_count:raise ValueError('mansion_parsed_count_mismatch')
                rows.extend(parsed)
        page_receipts.append({'page':page,**info,'cards':len(cards),'url':url})
        print(json.dumps({'stage':'mansion_page','municipality':name,'kind':kind,'page':page,'max_page':max_page,'rows_so_far':len(rows)},ensure_ascii=False),flush=True)
        page+=1
    if len(buildings)!=expected:raise ValueError('mansion_total_buildings_mismatch')
    # Provider listing IDs may appear under multiple building-name aliases.
    # Keep every observation for the canonical-stage duplicate/conflict check.
    return {'municipality':name,'kind':kind,'city_id':city_id,'status':'success',
        'zero_confirmation':'not_asserted_from_missing_rows',
        'buildings':len(buildings),'rows':rows,'pages':page_receipts,'parser_version':VERSION}


def collect(fetcher, only=None):
    results=[];catalogs={}
    for kind in ('chintai','mansion'):
        catalogs[kind]=catalog(fetcher.get(BASE+f'/{kind}/prefecture/40.html'),kind)
        for name in MUNICIPALITIES:
            if only and name not in only:continue
            entry=catalogs[kind].get(name)
            scope=fetcher.work/(kind+'-'+hashlib.sha256(name.encode()).hexdigest()[:12]+'.scope.json')
            if fetcher.store and not scope.exists():
                from tatemono_map.cloud.realpro_weekly import read_json
                saved=read_json(fetcher.store,f'private-inputs/mansion-review/cycles/{fetcher.cycle}/scopes/{scope.name}')
                if saved:scope.write_text(json.dumps(saved,ensure_ascii=False))
            if scope.exists():
                previous=json.loads(scope.read_text())
                if previous.get('parser_version')==VERSION and previous['status'] in ('success','confirmed_zero','no_source_page'):
                    results.append(previous);continue
            if not entry:
                result={'municipality':name,'kind':kind,'status':'no_source_page','rows':[],
                    'reason':'not_linked_in_fresh_prefecture_catalog','parser_version':VERSION}
            else:
                try:result=collect_scope(fetcher,kind,name,entry)
                except Exception as e:
                    result={'municipality':name,'kind':kind,'city_id':entry['city_id'],'status':'failed','rows':[],
                        'reason':str(e).split('\n')[0][:150],'parser_version':VERSION}
            results.append(result);scope.write_text(json.dumps(result,ensure_ascii=False))
            if fetcher.store and result['status']!='failed':
                # Completed scope receipts allow task retries without any HTTP
                # repeat; raw HTTP receipts independently cover interrupted scopes.
                fetcher.store.upload_verified(scope,f'private-inputs/mansion-review/cycles/{fetcher.cycle}/scopes/{scope.name}')
            print(json.dumps({'stage':'mansion_scope',**{k:v for k,v in result.items() if k not in ('rows','pages')},'row_count':len(result['rows'])},ensure_ascii=False),flush=True)
    return results,catalogs
