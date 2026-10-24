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
    found={};diagnostics=[]
    for row in rows:
        matches=[]
        for raw in raw_by_url[row['source_url']]:
            if ''.join(row['name'].split()).casefold() not in ''.join(raw.split()).casefold():continue
            for evidence in ['',*refs[row['building_key']]]:
                material='|'.join(str(v or '').strip() for v in (row['name'],row['room_label'],row['address'],row['updated_at'],raw,evidence))
                if hashlib.sha1(material.encode()).hexdigest()==row['listing_key']:
                    matches.append(raw);break
        if len(matches)==1:found[row['listing_key']]=matches[0]
        elif len(diagnostics)<4:
            candidates=[r for r in raw_by_url[row['source_url']] if ''.join(row['name'].split()).casefold() in ''.join(r.split()).casefold()]
            diagnostics.append({'name':row['name'],'source_candidate_count':len(candidates),'evidence_count':len(refs[row['building_key']]),'tail_fields':[[p.strip()[:160] for p in raw.split('|')[-8:] if any(token in p for token in ('賃料','面積','間取','所在階','管理費'))] for raw in candidates[:2]]})
    return found,diagnostics


def numeric_fields(raw):
    fields={}
    # Only the row-specific trailing labeled fields qualify. General page text
    # and rent histories can contain other rooms and never authorize a repair.
    for part in raw.split('|')[1:]:
        m=re.fullmatch(r'\s*(賃料|家賃|面積|間取り|所在階|管理費)\s*[:：]\s*(.*?)\s*',part,re.S)
        if m:fields[m[1]]=m[2]
    return fields
