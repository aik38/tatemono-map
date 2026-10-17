"""Reuse the verified, previously acquired original; never simulate a live search."""
import json
from pathlib import Path

from tatemono_map.cloud.collector import CollectionError, Collected
from tatemono_map.cloud.public_db import sha256

PRESERVED_RUN='20261017T160944Z-10bd49a595a4'
PRESERVED_PDF_SHA='9879e17da1fd3ca1afcdf90cd4e7afda10f844bd8521197ae4a5be381687ae4d'


def reuse_verified(store, run, config, root):
    if run!=PRESERVED_RUN or config.get('company_id')!='8' or config.get('area_id')!='kitakyushu':
        raise CollectionError('preserved_acquisition_scope_invalid')
    root.mkdir(parents=True,exist_ok=True)
    def pinned(name,output):
        blob=store.bucket.blob(name);blob.reload()
        blob.download_to_filename(str(output),if_generation_match=int(blob.generation))
        return {'object':name,'generation':int(blob.generation),'sha256':sha256(output)}
    evidence_file=root/'original-evidence.json'
    ref=pinned(f'private-runs/{run}/collection-evidence.json',evidence_file)
    evidence=json.loads(evidence_file.read_text())
    if evidence.get('area_id')!='kitakyushu' or evidence.get('scope_verified') is not True or evidence.get('search_counts')!=[1045]:
        raise CollectionError('preserved_acquisition_evidence_invalid')
    if len(evidence.get('responses',[]))!=1 or evidence['responses'][0].get('content_type')!='application/pdf':
        raise CollectionError('preserved_acquisition_pdf_manifest_invalid')
    pdf=root/'ulucks-000.pdf';pdfref=pinned(f'private-runs/{run}/pdf/000.pdf',pdf)
    if pdfref['sha256']!=PRESERVED_PDF_SHA:
        raise CollectionError('preserved_acquisition_pdf_checksum_mismatch')
    evidence.update(reused_acquisition_run=run,original_evidence_ref=ref,original_pdf_ref=pdfref)
    return Collected([pdf],1045,False,evidence)
