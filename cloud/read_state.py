"""Read safe release aggregates through the existing Pages publisher identity."""
import json
import os
from google.cloud import storage

def main():
    blob=storage.Client().bucket(os.environ['GCP_BUCKET']).blob('state/current.json')
    blob.reload();generation=int(blob.generation)
    head=json.loads(blob.download_as_bytes(if_generation_match=generation))
    keys=('collection_mode','company_id','area_id','company_count','successful_companies','failed_companies','unavailable_companies','company_census',
        'parsed_rows','attached_rows','held_rows','anomaly_rows','duplicate_rows','retained_rows','row_counts',
        'pdf_count','new_buildings','matched_existing_rows','legacy_overlap_rows','managed_overlap_rows','cross_company_duplicate_rows',
        'counts_before','counts_after','public_counts','area_counts','acquired_at','processed_at','all_company_proof',
        'reused_acquisition_run','replayed_acquisition_companies','reused_companies','newly_acquired_pdf_count','historical_rows_preserved','integration_contract','acquisition_manifest_ref','company_ids','company_results')
    result={k:head.get(k) for k in ('schema','qc','run_id','source_commit','master','public')}
    result.update(generation=generation,report={k:head['report'][k] for k in keys if k in head.get('report',{})})
    print('CLOUD_STATE_SAFE_JSON='+json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
