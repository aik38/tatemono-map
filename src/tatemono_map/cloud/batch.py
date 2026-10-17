"""A complete live company census commits one master/public release by CAS."""
from __future__ import annotations

import json
import shutil
import copy
from datetime import datetime, timezone
from pathlib import Path

from tatemono_map.cloud.collector import CollectionError, validate_config
from tatemono_map.cloud.pipeline import update_master, validate_master
from tatemono_map.cloud.pipeline import unit_room
from tatemono_map.cloud.public_db import export_public, readonly, validate_public, snapshot_sqlite
from tatemono_map.cloud.storage import commit_release, validate_head
from tatemono_map.cloud.wide import collect_all


def public_proof(path: Path, affected: set[str]) -> list[dict]:
    with readonly(path) as conn:
        if not affected:
            # A successful batch may change only non-public buildings. Prove
            # preservation using an existing public building, without exposing
            # private IDs in the marker or inventing a public change.
            affected={conn.execute('SELECT building_id FROM buildings ORDER BY building_id LIMIT 1').fetchone()[0]}
        proof=[]
        fields=('building_key','vacancy_count','rent_yen_min','rent_yen_max','area_sqm_min','area_sqm_max','layout_types_json')
        for building in sorted(affected):
            row=conn.execute('SELECT '+','.join(fields)+' FROM building_summaries WHERE building_key=?',(building,)).fetchone()
            if row is None:
                raise CollectionError('batch_public_proof_building_missing')
            value=dict(zip(fields,row))
            value['layout_types']=json.loads(value.pop('layout_types_json') or '[]')
            fees=conn.execute('SELECT maint_yen_min,maint_yen_max FROM building_rental_summaries WHERE building_key=?',(building,)).fetchone()
            value.update(zip(('maint_yen_min','maint_yen_max'),fees or (None,None)))
            proof.append(value)
    return proof


def execute_all(store, config: dict, credentials: dict, work: Path, source_commit: str, *, collector=collect_all,reuse_release: str | None = None,replay_acquisition_run: str | None = None) -> dict:
    from tatemono_map.cloud.run import new_run_id
    validate_config(config)
    if config.get('collection_mode')!='all_companies' or config.get('area_id')!='kitakyushu':
        raise CollectionError('batch_target_contract_invalid')
    head,generation=store.read_head()
    validate_head(head)
    master=work/'master.sqlite3'
    baseline=work/'publication-baseline.sqlite3'
    store.download(head['master'],master)
    validate_master(master)
    with readonly(master) as conn:
        initial_buildings={row[0] for row in conn.execute('SELECT building_id FROM buildings')}
        initial_counts={t:conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('buildings','listings','sale_listings','raw_sources')}
    store.download(head['public'],baseline)
    if validate_public(baseline)!=head['report']['public_counts']:
        raise CollectionError('publication_baseline_counts_mismatch')
    previous=[]
    reference=head['report'].get('company_catalog_ref')
    if reference is not None:
        if reference.get('object')!=f"private-runs/{head['run_id']}/company-catalog.json":
            raise CollectionError('previous_company_catalog_reference_invalid')
        previous_file=work/'previous-company-catalog.json'
        store.download(reference,previous_file)
        if previous_file.stat().st_size>2*1024*1024:
            raise CollectionError('previous_company_catalog_too_large')
        previous=json.loads(previous_file.read_text())
        if not isinstance(previous,list) or len(previous)>5000:
            raise CollectionError('previous_company_catalog_invalid')
    run=new_run_id()
    store.upload(master,f'backups/{run}.sqlite3')
    print('ULUCKS_COLLECTION_SAFE='+json.dumps({'stage':'backup_verified','run_id':run}),flush=True)
    reports=[]
    cached={}
    if reuse_release:
        if reuse_release!=head['run_id']:
            raise CollectionError('resume_head_changed')
        if head['report'].get('company_id')=='8' and head['report'].get('area_id')=='kitakyushu':
            cached['8']=copy.deepcopy(head['report'])
        elif head['report'].get('collection_mode')=='all_companies':
            for entry in head['report'].get('company_results',[]):
                path=work/('cached-'+entry['company_id']+'.json')
                store.download(entry['result_ref'],path)
                cached[entry['company_id']]=json.loads(path.read_text())
    affected=set()
    fresh_units=set()
    trace={'run_id':run,'company_count':None,'active_company':None,'completed':[],'failed':[]}
    def save_json(value,name):
        file=work/(name+'.json')
        file.write_text(json.dumps(value,ensure_ascii=False))
        return store.upload(file,f'private-runs/{run}/{name}.json')
    def process_company(one,result):
        if one is None:
            trace['company_count']=len(result)
            trace['company_census']=getattr(result,'counts',{})
            trace['excluded_companies']=getattr(result,'excluded',[])
            trace['company_catalog_ref']=save_json(result,'company-catalog')
            missing=set(head['report'].get('company_ids',[]))-{x['company_id'] for x in result}-set(getattr(result,'counts',{}).get('unavailable_previous_ids',[]))
            if missing:
                trace['missing_previously_active_companies']=sorted(missing)
                raise CollectionError('company_catalog_missing_previously_active_company')
            return
        company_id=one['company_id']
        if result is None:
            trace['active_company']=company_id
            return
        directory=work/'companies'/company_id
        directory.mkdir(parents=True,exist_ok=True)
        pdf_refs=[]
        for index,pdf in enumerate(result.pdfs):
            pdf_refs.append(store.upload(pdf,f'private-runs/{run}/companies/{company_id}/pdf/{index:03d}.pdf'))
        evidence_ref=save_json(result.evidence,'company-'+company_id+'-evidence')
        manifest_ref=save_json({'config':one,'pdfs':pdf_refs,'evidence':evidence_ref,'expected_rows':result.expected_rows,
            'confirmed_zero':result.confirmed_zero},'company-'+company_id+'-manifest')
        from tatemono_map.cli.pdf_batch_run import page_count_fast
        print('ULUCKS_COLLECTION_SAFE='+json.dumps({'stage':'pdf_acquired','run_id':run,'pdf_count':len(result.pdfs),
            'pdf_pages':sum(page_count_fast(pdf) for pdf in result.pdfs),'expected_rows':result.expected_rows,
            'completed_companies':len(reports)}),flush=True)
        # Each source has its own immutable run and current pointer. No failed
        # acquisition becomes zero; a failure prevents the final head commit.
        report=update_master(master,result.pdfs,result.expected_rows,one,directory,run+'-company-'+company_id,
            confirmed_zero=result.confirmed_zero,public_baseline=baseline)
        report['acquisition_manifest_ref']=manifest_ref
        report.update(company_id=company_id,area_id='kitakyushu',acquired_at=result.evidence.get('acquired_at'))
        if result.evidence.get('replayed_acquisition_run'):
            report['replayed_acquisition_run']=result.evidence['replayed_acquisition_run']
        review=directory/'review-rows.private.csv'
        if review.exists():report['review_ref']=store.upload(review,f'private-runs/{run}/companies/{company_id}/review-rows.csv')
        with readonly(master) as conn:
            from tatemono_map.normalize.effective_rentals import canonical_key
            aliases=dict(conn.execute('SELECT alias_key,canonical_key FROM building_key_aliases'))
            units=[(canonical_key(b,aliases),unit_room(room,explicit_labels=True)) for b,room in conn.execute(
                'SELECT building_key,room_label FROM listings WHERE ingest_run_id=?',(report['ingest_run_id'],))]
            report['matched_existing_rows_at_batch_start']=sum(b in initial_buildings for b,_ in units)
            fresh_units.update(units)
        reports.append(report)
        affected.update(row['building_key'] for row in report['proof'])
        result_ref=save_json(report,'company-'+company_id+'-result')
        trace['completed'].append({'company_id':company_id,'parsed_rows':report['parsed_rows'],'result_ref':result_ref,'manifest_ref':manifest_ref,
            'pdf_count':report['pdf_count'],'new_buildings':report['counts_after']['buildings']-report['counts_before']['buildings'],
            'overlap_rows':report['legacy_overlap_rows']})
        trace['active_company']=None
        print('ULUCKS_BATCH_SAFE='+json.dumps({'stage':'company_complete','completed':len(reports),
            'company_count':trace['company_count'],'parsed_rows':sum(r['parsed_rows'] for r in reports)}),flush=True)
        save_json(trace,'checkpoint-'+company_id)
    def failure(one,error):
        trace['failed'].append({'company_id':one['company_id'],'code':str(error)})
        trace['active_company']=None
        save_json(trace,'failed-company-'+one['company_id'])
        print('ULUCKS_BATCH_SAFE='+json.dumps({'stage':'company_failed','completed':len(reports),'company_count':trace['company_count'],
            'run_id':run,'company_id':one['company_id'],'code':str(error)}),flush=True)
    def company(one,result):
        if isinstance(result,CollectionError):
            failure(one,result)
            return
        if one is not None and result is None and one['company_id'] in cached:
            report=cached[one['company_id']]
            from tatemono_map.cloud.fetch_public import accounted_collection
            try:age=(datetime.now(timezone.utc)-datetime.fromisoformat(report.get('acquired_at','').replace('Z','+00:00'))).total_seconds()
            except (ValueError,TypeError):age=-1
            with readonly(master) as conn:
                active=conn.execute('SELECT ingest_run_id FROM current_ingest_snapshots WHERE source=?',(report.get('scope_key'),)).fetchone()
                units=conn.execute('SELECT building_key,room_label FROM listings WHERE ingest_run_id=?',(report.get('ingest_run_id'),)).fetchall()
                from tatemono_map.normalize.effective_rentals import canonical_key
                aliases=dict(conn.execute('SELECT alias_key,canonical_key FROM building_key_aliases'))
                units=[(canonical_key(b,aliases),room) for b,room in units]
            if (0<=age<=24*3600 and active and active[0]==report.get('ingest_run_id')
                and report.get('integration_contract')=='ulucks-partial-v1' and accounted_collection(report)):
                report.update(reused_scope=True,reused_from_release=reuse_release,
                    matched_existing_rows_at_batch_start=sum(b in initial_buildings for b,room in units))
                fresh_units.update((b,unit_room(room,explicit_labels=True)) for b,room in units)
                reports.append(report)
                affected.update(row['building_key'] for row in report['proof'])
                ref=save_json(report,'company-'+one['company_id']+'-result')
                trace['completed'].append({'company_id':one['company_id'],'parsed_rows':report['parsed_rows'],
                    'result_ref':ref,'manifest_ref':report.get('acquisition_manifest_ref'),'reused_scope':True})
                save_json(trace,'checkpoint-'+one['company_id'])
                print('ULUCKS_BATCH_SAFE='+json.dumps({'stage':'verified_scope_reused','completed':len(reports),'company_count':trace['company_count']}),flush=True)
                return True
        if one is not None and result is None and replay_acquisition_run:
            from tatemono_map.cloud.replay import replay_company
            try:saved=replay_company(store,replay_acquisition_run,one,config,work/'replay'/one['company_id'])
            except CollectionError as exc:
                failure(one,exc)
                return True
            if saved is not None:
                company(*saved)
                return True
        if one is None or result is None:
            return process_company(one,result)
        backup_file=work/'company-rollback.sqlite3'
        snapshot_sqlite(master,backup_file)
        try:
            process_company(one,result)
        except CollectionError as exc:
            # Only this disposable company's changes are rolled back. Other
            # companies keep their accepted updates; the failed scope stays old.
            import gc,traceback
            code=str(exc)
            traceback.clear_frames(exc.__traceback__)
            exc.__traceback__=None
            gc.collect()
            for file in (master,Path(str(master)+'-wal'),Path(str(master)+'-shm')):file.unlink(missing_ok=True)
            shutil.copyfile(backup_file,master)
            failure(one,CollectionError(code))
        finally:
            backup_file.unlink(missing_ok=True)
    try:
        catalog=collector({**config,'previous_verified_companies':previous},credentials,work/'pdf',company)
        if not catalog or len(reports)+len(trace['failed'])!=len(catalog) or len({x['company_id'] for x in catalog})!=len(catalog):
            raise CollectionError('all_companies_census_incomplete')
        if not reports:raise CollectionError('all_companies_failed')
        counts=export_public(master,work/'public.sqlite3',baseline=baseline)
        with readonly(master) as conn:
            final_counts={t:conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in initial_counts}
        proof=public_proof(work/'public.sqlite3',affected)
        total=sum(r['parsed_rows'] for r in reports)
        pdfs=sum(r['pdf_count'] for r in reports)
        report={'collection_mode':'all_companies','area_id':'kitakyushu','company_count':len(catalog),
            'integration_contract':'ulucks-partial-v1',
            'row_counts':{k:sum(r['row_counts'].get(k,0) for r in reports) for k in ('accepted_existing','accepted_new','held','anomaly','duplicate')},
            'company_census':getattr(catalog,'counts',{}),
            'company_ids':[x['company_id'] for x in catalog],
            'company_catalog_ref':trace['company_catalog_ref'],
            'successful_companies':len(reports),'parsed_rows':total,'attached_rows':sum(r['attached_rows'] for r in reports),
            'failed_companies':trace['failed'],'company_results':trace['completed'],
            'pdf_count':pdfs,'pdfs':[p for r in reports for p in r['pdfs']],
            'acquisition_status':'pdf_verified' if pdfs else 'confirmed_zero',
            'counts_before':initial_counts,'counts_after':final_counts,
            'reused_companies':sum(bool(r.get('reused_scope')) for r in reports),
            'replayed_acquisition_companies':sum(bool(r.get('replayed_acquisition_run')) for r in reports),
            'newly_acquired_pdf_count':sum(r['pdf_count'] for r in reports if not r.get('reused_scope') and not r.get('replayed_acquisition_run')),
            'legacy_overlap_rows':sum(r['legacy_overlap_rows'] for r in reports),
            'managed_overlap_rows':sum(r.get('managed_overlap_rows',0) for r in reports),
            'matched_existing_rows':sum(r.get('matched_existing_rows_at_batch_start',0) for r in reports),
            'cross_company_duplicate_rows':sum(r['attached_rows'] for r in reports)-len(fresh_units),
            'held_rows':sum(r.get('held_rows',0) for r in reports),
            'anomaly_rows':sum(r.get('anomaly_rows',0) for r in reports),
            'duplicate_rows':sum(r.get('duplicate_rows',0) for r in reports),
            'retained_rows':sum(r.get('retained_rows',0) for r in reports),
            'new_buildings':final_counts['buildings']-initial_counts['buildings'],
            'historical_rows_preserved':True,'public_counts':counts,'proof':proof,
            'processed_at':datetime.now(timezone.utc).isoformat()}
        if not trace['failed']:
            report['all_company_proof']={'run_id':run,'source_commit':source_commit,'company_count':len(catalog)}
        else:
            from tatemono_map.cloud.run import all_company_proof_ready
            if all_company_proof_ready(head,source_commit):
                report['all_company_proof']=head['report'].get('all_company_proof') or {'run_id':head['run_id'],'source_commit':source_commit,'company_count':head['report']['company_count']}
        save_json(trace,'batch-result')
        return commit_release(store,work,run,generation,report,source_commit)
    except CollectionError as exc:
        trace.update(code=str(exc),previous_head_unchanged=store.read_head()==(head,generation))
        try:
            save_json(trace,'batch-failure')
            review=work/'companies'/str(trace['active_company'])/'overlap-review.private.json'
            if review.is_file():
                store.upload(review,f'private-runs/{run}/overlap-review.json')
            for review in Path('tmp/review').glob('*.csv'):
                if review.stat().st_size <= 10 * 1024 * 1024:
                    store.upload(review,f'private-runs/{run}/review/{review.name}')
        except Exception:
            pass
        print('ULUCKS_BATCH_SAFE='+json.dumps({'stage':'failed','completed':len(reports),'company_count':trace['company_count'],'run_id':run,'code':str(exc)}),flush=True)
        exc.run_id=run
        raise
