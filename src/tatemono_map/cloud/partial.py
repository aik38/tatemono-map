"""Private row audit, confirmed review decisions, and conservative carry-forward."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from collections import defaultdict

from tatemono_map.building_registry.common import insert_unmatched_queue
from tatemono_map.building_registry.normalization import normalize_address_for_matching, normalize_ulucks_name


def literal_room(value):
    text = re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or ''))).upper()
    text = text.removesuffix('号室')
    return text if re.fullmatch(r'[A-Z0-9]+(?:-[A-Z0-9]+)*(?:棟)?', text) else None


def review_key(scope, name, address, room):
    value = [scope, name, address, unicodedata.normalize('NFKC', str(room or '')).strip()]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


class PartialIngest:
    def __init__(self, conn, scope, run, company, anomalies=None):
        from tatemono_map.normalize.effective_rentals import effective_rentals
        self.conn, self.scope, self.run, self.company = conn, scope, run, company
        self.rows = {}
        self.anomalies = anomalies or {}
        self.initial = {r[0] for r in conn.execute('SELECT building_id FROM buildings')}
        self.decisions = {r[0]: tuple(r[1:]) for r in conn.execute('SELECT review_key,decision,building_id,room_label FROM cloud_review_decisions')}
        reviewed=defaultdict(set)
        for payload,building in conn.execute("SELECT c.raw_json,d.building_id FROM cloud_review_decisions d JOIN cloud_collection_rows c ON c.review_key=d.review_key WHERE d.decision='match'"):
            raw=json.loads(payload)
            reviewed[(normalize_ulucks_name(raw.get('building_name','')),normalize_address_for_matching(raw.get('address','')))].add(building)
        self.reviewed_buildings={pair:next(iter(ids)) for pair,ids in reviewed.items() if len(ids)==1}
        self.blocked_legacy = {r['building_key'] for r in effective_rentals(conn)
            if r['source_kind']=='ulucks' and literal_room(r['room_label']) is None}

    def begin(self, row, normalized, evidence):
        key = review_key(self.scope, normalized.normalized_name, normalized.normalized_address, row.get('room'))
        item = {'row':dict(row), 'normalized':normalized, 'review_key':key, 'classification':None,
            'building_id':None, 'listing_key':None, 'reason':'', 'candidates':[]}
        self.rows[evidence] = item
        decision = self.decisions.get(key)
        if decision and decision[0]=='block':
            self.hold(evidence, 'reviewed_block', [decision[1]] if decision[1] else [])
            return False, None
        room = literal_room(decision[2] if decision and decision[2] else row.get('room'))
        reason = self.anomalies.get(evidence)
        if reason or not normalized.raw_name or not normalized.raw_address:
            self.hold(evidence, reason or 'invalid_identity_field', anomaly=True)
            return False, None
        if room is None:
            self.hold(evidence, 'room_identity_ambiguous')
            return False, None
        row['room'] = room
        confirmed=decision[1] if decision and decision[0]=='match' else self.reviewed_buildings.get((normalized.normalized_name,normalized.normalized_address))
        return True, confirmed

    def hold(self, evidence, reason, candidates=None, *, anomaly=False):
        item=self.rows[evidence]; n=item['normalized']
        ids=list(dict.fromkeys(candidates or []))
        item.update(classification='anomaly' if anomaly else 'held',reason=reason,candidates=ids)
        insert_unmatched_queue(self.conn, source='ulucks', ingest_run_id=self.run, evidence_id=evidence,
            raw_name=n.raw_name, raw_address=n.raw_address, normalized_name=n.normalized_name,
            normalized_address=n.normalized_address, reason=reason, candidate_building_ids='|'.join(ids))

    def accepted(self, evidence, building, listing):
        self.rows[evidence].update(classification='accepted_existing' if building in self.initial else 'accepted_new',
            building_id=building,listing_key=listing)

    def finish(self):
        queued={r[0]:tuple(r[1:]) for r in self.conn.execute(
            'SELECT evidence_id,reason,candidate_building_ids FROM unmatched_queue WHERE ingest_run_id=? ORDER BY id',(self.run,))}
        for evidence,item in self.rows.items():
            if item['classification'] is None:
                if evidence not in queued:raise RuntimeError('untracked_collection_row')
                reason, ids=queued[evidence]
                item.update(classification='held',reason=reason,candidates=(ids or '').split('|') if ids else [])
        # Candidates below are review aids only. They never authorize a match.
        from difflib import SequenceMatcher
        candidates=[(r[0],normalize_ulucks_name(r[1] or ''),normalize_address_for_matching(r[2] or ''))
            for r in self.conn.execute('SELECT building_id,canonical_name,canonical_address FROM buildings')]
        ranked_cache={}
        for evidence,item in self.rows.items():
            if item['classification'] not in ('held','anomaly') or item['candidates']:continue
            n=item['normalized'];pair=(n.normalized_name,n.normalized_address)
            if pair not in ranked_cache:
                ranked=[]
                for building,name,address in candidates:
                    score=0.65*SequenceMatcher(None,n.normalized_address,address).ratio()+0.35*SequenceMatcher(None,n.normalized_name,name).ratio()
                    if score>=0.70:ranked.append((score,building))
                ranked_cache[pair]=sorted(ranked,reverse=True)[:3]
            ranked=ranked_cache[pair];item['candidates']=[b for score,b in ranked]
            self.conn.execute('UPDATE unmatched_queue SET candidate_building_ids=?,candidate_scores=? WHERE ingest_run_id=? AND evidence_id=?',
                ('|'.join(item['candidates']),'|'.join(str(round(score,4)) for score,b in ranked),self.run,evidence))
        groups=defaultdict(list)
        for evidence,item in self.rows.items():
            if item['listing_key']:
                row=self.conn.execute('SELECT building_key,room_label,rent_yen,maint_yen,layout,area_sqm,availability_raw,deposit_text,key_money_text FROM listings WHERE listing_key=? AND ingest_run_id=?',(item['listing_key'],self.run)).fetchone()
                groups[(row[0],literal_room(row[1]))].append((evidence,tuple(row[2:])))
        for (building,room),items in groups.items():
            if len(items)<2:continue
            same=len({terms for evidence,terms in items})==1
            for evidence,terms in items[1:] if same else items:
                item=self.rows[evidence]
                self.conn.execute('DELETE FROM listings WHERE listing_key=? AND ingest_run_id=?',(item['listing_key'],self.run))
                if same:item.update(classification='duplicate',reason='same_company_identical_offer')
                else:self.hold(evidence,'same_company_conflicting_offer',[building])
        # Building attributes must also come exclusively from final accepted
        # rows. Provisional conflicting offers cannot leak via buildings.
        for item in self.rows.values():
            if item['classification'] not in ('accepted_existing','accepted_new'):continue
            r=self.conn.execute('SELECT structure_raw,structure,built_age_years,age_years,built_year_month,availability_raw,move_in_date FROM listings WHERE listing_key=? AND ingest_run_id=?',(item['listing_key'],self.run)).fetchone()
            year=int(r[4][:4]) if r[4] and str(r[4])[:4].isdigit() else None
            self.conn.execute("""UPDATE buildings SET structure=COALESCE(NULLIF(?,''),structure),
                age_years=COALESCE(?,age_years),built_year=COALESCE(?,built_year),
                availability_raw=COALESCE(NULLIF(?,''),availability_raw),availability_label=COALESCE(NULLIF(?,''),availability_label),
                updated_at=CURRENT_TIMESTAMP WHERE building_id=?""",(r[0] or r[1],r[2] if r[2] is not None else r[3],year,r[5],r[6],item['building_id']))
        for evidence,item in self.rows.items():
            n=item['normalized']
            self.conn.execute('INSERT INTO cloud_collection_rows VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(
                self.scope,self.run,evidence,self.company,item['review_key'],item['classification'],item['building_id'],
                item['row'].get('room',''),json.dumps(item['row'],ensure_ascii=False),item['reason'],
                json.dumps(item['candidates']),item['listing_key']))
        counts=defaultdict(int)
        for item in self.rows.values():counts[item['classification']]+=1
        return dict(counts)


def retain_pending(conn, scope, retired, run, output):
    """Retain only previously active, company-owned offers; never claim unknowns."""
    scopes=[scope,*retired]
    marks=','.join('?' for _ in scopes)
    old=conn.execute(f'''SELECT DISTINCT l.* FROM listings l JOIN ingest_runs r ON r.id=l.ingest_run_id
        WHERE l.source_kind='ulucks' AND (
          (r.source IN ({marks}) AND l.ingest_run_id IN (SELECT ingest_run_id FROM current_ingest_snapshots))
          OR EXISTS (SELECT 1 FROM cloud_retained_listings h JOIN current_ingest_snapshots s
            ON s.source=h.scope_key AND s.ingest_run_id=h.ingest_run_id
            WHERE h.listing_key=l.listing_key AND h.scope_key IN ({marks})))''',(*scopes,*scopes)).fetchall()
    fresh={(r[0],literal_room(r[1])) for r in conn.execute('SELECT building_key,room_label FROM listings WHERE ingest_run_id=?',(run,))}
    identities=[(r['building_id'],normalize_ulucks_name(r['canonical_name'] or ''),normalize_address_for_matching(r['canonical_address'] or ''))
        for r in conn.execute('SELECT building_id,canonical_name,canonical_address FROM buildings')]
    held=conn.execute("SELECT * FROM cloud_collection_rows WHERE ingest_run_id=? AND classification IN ('held','anomaly')",(run,)).fetchall()
    keep={}
    for item in held:
        raw=json.loads(item['raw_json']); name=normalize_ulucks_name(raw.get('building_name',''))
        address=normalize_address_for_matching(raw.get('address',''))
        # Fuzzy review suggestions cannot narrow the preservation boundary.
        uncertain=item['reason'].startswith(('unmatched','room_identity','invalid'))
        candidates=set() if uncertain else set(json.loads(item['candidate_ids_json']))
        candidates.update(b for b,n,a in identities if (name and n==name) or (address and a==address))
        room=literal_room(raw.get('room'))
        for listing in old:
            identity=(listing['building_key'],literal_room(listing['room_label']))
            if identity in fresh:continue
            # Unknown building identity cannot authorize ending any old offer
            # from this company's previous snapshot. Other scopes still update.
            if candidates and listing['building_key'] not in candidates:continue
            if candidates and room and identity[1] and identity[1]!=room:continue
            keep[listing['listing_key']]=item['evidence_id']
    conn.executemany('INSERT INTO cloud_retained_listings VALUES (?,?,?,?)',[(k,scope,run,e) for k,e in keep.items()])
    columns=('evidence_id','company_id','review_key','classification','raw_name','raw_address','room_raw','reason',
        'candidate_ids_json','decision','building_id','room_label','reviewer','raw_json')
    with output.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
        for row in held:
            raw=json.loads(row['raw_json'])
            writer.writerow({**{c:row[c] for c in columns if c in row.keys()},
                'raw_name':raw.get('building_name',''),'raw_address':raw.get('address',''),
                'decision':'','building_id':'','room_label':'','reviewer':''})
    return len(keep)


def confirm_review(conn, key, decision, building, room, reviewer):
    if decision not in ('match','block') or not reviewer.strip():raise ValueError('review_confirmation_required')
    if not conn.execute('SELECT 1 FROM cloud_collection_rows WHERE review_key=?',(key,)).fetchone():raise ValueError('review_row_missing')
    if building and not conn.execute('SELECT 1 FROM buildings WHERE building_id=?',(building,)).fetchone():raise ValueError('review_building_missing')
    if decision=='match' and (not building or not literal_room(room)):raise ValueError('review_identity_incomplete')
    conn.execute('INSERT INTO cloud_review_decisions VALUES (?,?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(review_key) DO UPDATE SET decision=excluded.decision,building_id=excluded.building_id,room_label=excluded.room_label,reviewer=excluded.reviewer,reviewed_at=excluded.reviewed_at',
        (key,decision,building,literal_room(room),reviewer.strip()))
    conn.execute("INSERT INTO raw_sources(provider,source_kind,source_url,content) VALUES ('manual_review','review',?,?)",(key,json.dumps({'decision':decision,'building_id':building,'room_label':literal_room(room),'reviewer':reviewer.strip()},ensure_ascii=False)))
    conn.execute('''UPDATE unmatched_queue SET status=?,resolved_building_id=?,resolved_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
        WHERE EXISTS (SELECT 1 FROM cloud_collection_rows c WHERE c.review_key=? AND c.ingest_run_id=unmatched_queue.ingest_run_id AND c.evidence_id=unmatched_queue.evidence_id)''',
        ('resolved' if decision=='match' else 'blocked',building,key))
