"""Controlled quality release using the inherited current canonical master."""
import base64,json,os,zlib
from tatemono_map.cloud.quality import release
from tatemono_map.cloud.storage import GCSStore
result=release(GCSStore(os.environ['GCP_BUCKET']),'work/quality',os.environ['QUALITY_SOURCE_COMMIT'],1792811980879908,commit=os.environ['QUALITY_MODE']=='commit')
import sqlite3
from tatemono_map.cloud.legacy_rent_evidence import locate,numeric_fields
c=sqlite3.connect('work/quality/master.sqlite3');c.row_factory=sqlite3.Row
missing=[dict(r) for r in c.execute("SELECT * FROM listings WHERE ingest_run_id=31 AND source_kind='mansion_review_chintai' AND rent_yen IS NULL AND area_sqm IS NULL")]
found,diagnostics=locate(c,missing)
from collections import Counter
result['legacy_original_evidence']={'matched_rows':len(found),'diagnostics':diagnostics,'field_counts':{str(k):v for k,v in Counter(tuple(numeric_fields(raw)) for raw in found.values()).items()},'samples':[numeric_fields(raw) for raw in list(found.values())[:8]]}
encoded=base64.b64encode(zlib.compress(json.dumps(result,ensure_ascii=False).encode())).decode()
for i in range(0,len(encoded),8000):print('QUALITY_AUDIT_CHUNK='+str(i//8000)+':'+encoded[i:i+8000],flush=True)
print('QUALITY_AUDIT_END='+str((len(encoded)+7999)//8000),flush=True)
