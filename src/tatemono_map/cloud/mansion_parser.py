"""Public list HTML and its public 'show all' fragments; no login data.

Column spans are expanded before mapping headers. A mosaic row is kept as
evidence but its hidden values are never reconstructed or used numerically.
"""
from __future__ import annotations
import base64
import hashlib
import re
import unicodedata
from decimal import Decimal
from urllib.parse import urljoin, urlsplit
from selectolax.parser import HTMLParser

BASE = 'https://www.mansion-review.jp'
VERSION = 'mansion-public-20261025-v1'


def text(node):
    return re.sub(r'\s+', ' ', node.text(separator=' ', strip=True) if node else '').strip()


def catalog(html, kind):
    tree = HTMLParser(html)
    if not tree.css_first('h1') or '福岡県' not in text(tree.css_first('h1')):
        raise ValueError('mansion_catalog_not_verified')
    found = {}
    for a in tree.css('a[href]'):
        url = urljoin(BASE, a.attributes.get('href') or '')
        m = re.fullmatch(rf'{BASE}/{kind}/city/(\d+)\.html', url)
        label = text(a)
        if m and label.endswith(('の賃貸','のマンション')):
            name = re.sub(r'の(?:賃貸|マンション)$', '', label)
            found[name] = {'city_id':m[1], 'url':url}
    if len(found) < 20:
        raise ValueError('mansion_catalog_incomplete')
    return found


def page_info(html, kind, city_id, name):
    tree = HTMLParser(html)
    title = text(tree.css_first('h1'))
    if name not in title or ('賃貸' if kind == 'chintai' else '中古マンション') not in title:
        raise ValueError('mansion_wrong_municipality_or_error_page')
    cards = tree.css('.searchResultList > li.property-detail-list-item')
    # Result counts describe buildings, not the number of advertised rooms.
    visible = ' '.join(text(n) for n in tree.css('li'))
    m = re.search(r'(\d[\d,]*)\s*[～〜]\s*(\d[\d,]*)\s*件[／/]\s*(\d[\d,]*)\s*件中', visible)
    if not m:
        if not cards and re.search(r'(?:該当|検索結果|物件)[^。]{0,30}(?:ありません|0\s*件)', text(tree.body)):
            return tree, cards, {'first':0,'last':0,'total':0,'max_page':1}
        raise ValueError('mansion_result_count_missing')
    first,last,total = (int(v.replace(',','')) for v in m.groups())
    if len(cards) != last-first+1:
        raise ValueError('mansion_card_count_mismatch')
    pages = [1]
    for a in tree.css('a[href]'):
        p = re.search(rf'/{kind}/city/{city_id}_(\d+)\.html(?:$|[?#])', a.attributes.get('href') or '')
        if p: pages.append(int(p[1]))
    return tree,cards,{'first':first,'last':last,'total':total,'max_page':max(pages)}


def facts(card):
    values = {}
    for tr in card.css('.property-detail-content_main tr'):
        th,td=tr.css_first('th'),tr.css_first('td')
        if th and td: values[text(th)] = text(td)
    title = card.css_first('.property-detail-content__head-title a')
    if not title: raise ValueError('mansion_building_title_missing')
    url = source_link(title)
    if not re.fullmatch(BASE+r'/mansion/\d+\.html',url): raise ValueError('mansion_building_url_missing')
    return {'building_name':text(title),'building_url':url,'address':values.get('住所') or values.get('所在地',''),
        'built_raw':values.get('築年数') or values.get('築年月',''),'structure':values.get('構造',''),
        'access':values.get('交通',''),'floor_count':values.get('階建て') or values.get('階建',''),
        'total_units':values.get('総戸数','')}


def more_request(wrap, button, kind, html):
    mid=wrap.attributes.get('data-id')
    if not mid or not mid.isdigit(): raise ValueError('mansion_more_building_id_missing')
    n=re.search(r'全\s*([\d,]+)\s*件',text(button))
    if not n: raise ValueError('mansion_more_expected_count_missing')
    params={'mansion_id':mid,'view_num':button.attributes.get('data-view-num','3')}
    for attr,key in [('data-mode','mode'),('data-kodawari-id','kodawari_id'),('data-apply-search-condition','apply_search_condition')]:
        if wrap.attributes.get(attr):params[key]=wrap.attributes[attr]
    if kind=='chintai':
        key=re.search(r'window\._g_cla\s*=\s*["\']([^"\']+)',html)
        if key:params['_cla']=key[1]
    endpoint='rental' if kind=='chintai' else 'sales'
    return BASE+f'/api/{endpoint}_recommend_search_more/index.php',params,int(n[1].replace(',',''))


def money(value):
    s=unicodedata.normalize('NFKC',value).replace(',','').replace(' ','')
    if re.search(r'万円台|モザイク|会員|応相談|非公開|未定',s):return None
    m=re.fullmatch(r'(\d+(?:\.\d+)?)(万円|円)',s)
    return int(Decimal(m[1])*(10000 if m[2]=='万円' else 1)) if m else None


def source_link(a):
    if a is None:return ''
    href=a.attributes.get('href','')
    if href.startswith(('https://','http://','/chintai/','/chuko/')):return urljoin(BASE,href)
    for key,value in a.attributes.items():
        if key.startswith('data-'):
            try: decoded=base64.b64decode(value,validate=True).decode('utf-8')
            except Exception:continue
            if re.fullmatch(BASE+r'/(?:chintai|chuko|mansion)/[\d/]+\.html',decoded):return decoded
    return ''


def parse_rows(table, rows, building, kind, page_url):
    if not rows:return []
    header=table.css_first('tr')
    columns=['image','listing']
    for th in header.css('th'):
        if 'size_title' in th.attributes.get('class',''):continue
        columns.extend([text(th).replace(' ','')]*int(th.attributes.get('colspan','1')))
    required={'賃料(管理費)','専有面積','間取り','所在階'} if kind=='chintai' else {'価格','専有面積','間取り','所在階'}
    if not required <= set(columns):raise ValueError('mansion_unknown_table_columns')
    result=[]
    for index,tr in enumerate(rows):
        cells=tr.css('td')
        expanded=[]
        for td in cells:expanded.extend([text(td)]*int(td.attributes.get('colspan','1')))
        mapped=dict(zip(columns,expanded))
        mosaic=bool(tr.css_first('.mosaic_cell')) or 'モザイク' in text(tr) or '万円台' in mapped.get('価格','')
        anchor=next((a for a in tr.css('a') if source_link(a)),None)
        url=source_link(anchor)
        title=text(anchor)
        room=''
        room_match=re.search(r'(?:\s|　)([A-Za-z]?\d+[A-Za-z]?(?:号室)?)$',unicodedata.normalize('NFKC',title))
        if room_match:room=room_match[1].removesuffix('号室')
        numeric=mapped.get('賃料(管理費)' if kind=='chintai' else '価格','')
        rentpart=re.split(r'[（(]',numeric)[0].strip()
        fee=re.search(r'[（(]\s*(.*?)\s*[)）]',numeric)
        area=re.fullmatch(r'(\d+(?:\.\d+)?)\s*(?:m²|m2|㎡)',mapped.get('専有面積',''))
        value=money(rentpart) if not mosaic else None
        area_value=float(area[1]) if area and not mosaic else None
        reason='hidden_terms' if mosaic else ''
        if not mosaic and (len(expanded)<len(columns) or any(not v for v in (building['building_name'],building['address']))):reason='invalid_row_context'
        if not reason and (value is None or area_value is None):reason='missing_exact_price_or_area'
        if not reason and not (0<value<=(10000000 if kind=='chintai' else 10000000000) and 5<=area_value<=2000):reason='numeric_out_of_range'
        if not reason and not url:reason='source_listing_identity_missing'
        item={**building,'kind':kind,'source_url':url,'page_url':page_url,'room':room,'price_yen':value,
            'fee_yen':money(fee[1]) if fee and not mosaic else None,'area_sqm':area_value,
            'layout':mapped.get('間取り','') if not mosaic else '', 'floor':mapped.get('所在階','') if not mosaic else '',
            'direction':mapped.get('向き','') if not mosaic else '', 'deposit':mapped.get('敷金',''),'key_money':mapped.get('礼金',''),
            'reason':reason,'raw':text(tr),'listing_title':title}
        identity=url or building['building_url']+'#hidden='+str(index)+':'+hashlib.sha256(text(tr).encode()).hexdigest()[:16]
        item['evidence_id']='mansion_review:'+kind+':'+identity
        result.append(item)
    return result
