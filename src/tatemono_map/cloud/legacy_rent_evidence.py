"""Locate a legacy import row by its original hash, never by similar price/unit."""
import hashlib
import re
from collections import defaultdict


def locate(conn, rows):
    refs=defaultdict(set)
    for b,e in conn.execute("SELECT building_id,evidence_id FROM building_sources WHERE source='mansion_review_list'"):
        refs[b].add(e)
    raw_by_url=defaultdict(set)
    for url,content in conn.execute("SELECT source_url,content FROM raw_sources WHERE provider='mansion_review_list'"):
        raw_by_url[url].add(content)
    folded_by_url={url:[(raw,''.join(raw.split()).casefold()) for raw in contents] for url,contents in raw_by_url.items()}
    found={};diagnostics=[]
    for row in rows:
        matches=[]
        folded_name=''.join(row['name'].split()).casefold()
        candidates=[raw for raw,folded in folded_by_url[row['source_url']] if folded_name in folded]
        for raw in candidates:
            for evidence in ['',*refs[row['building_key']]]:
                material='|'.join(str(v or '').strip() for v in (row['name'],row['room_label'],row['address'],row['updated_at'],raw,evidence))
                if hashlib.sha1(material.encode()).hexdigest()==row['listing_key']:
                    matches.append(raw);break
        if len(matches)==1:found[row['listing_key']]=matches[0]
        elif len(diagnostics)<4:
            diagnostics.append({'name':row['name'],'source_candidate_count':len(candidates),'evidence_count':len(refs[row['building_key']]),'tail_fields':[[p.strip()[:160] for p in raw.split('|')[-8:] if any(token in p for token in ('賃料','面積','間取','所在階','管理費'))] for raw in candidates[:2]]})
    return found,diagnostics


def numeric_fields(raw):
    fields={}
    # Only the row-specific trailing labeled fields qualify. General page text
    # and rent histories can contain other rooms and never authorize a repair.
    for part in raw.split('|')[1:]:
        m=re.fullmatch(r'\s*(賃料|家賃|面積|専有面積|間取り|所在階|管理費|敷金|礼金|共益費|物件名)\s*[:：]\s*(.*?)\s*',part,re.S)
        if m:fields[m[1]]=m[2]
    return fields


def shifted_terms(raw):
    """Decode only the audited legacy table shape, retaining one row's terms."""
    from decimal import Decimal
    f=numeric_fields(raw)
    rent=re.fullmatch(r"([0-9][0-9,]*(?:\.[0-9]+)?)万円\s*\(([0-9,]+|-)円\)",f.get('敷金',''))
    area=re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)m[²2]",f.get('間取り',''))
    if not rent or not area or not f.get('管理費') or re.search(r'[0-9]円',f['管理費']):return None
    amount=int(Decimal(rent[1].replace(',',''))*10000)
    sqm=float(area[1])
    if not 10000<=amount<=1000000 or not 5<=sqm<=500:return None
    return {'rent_yen':amount,'area_sqm':sqm}
