"""Controlled quality release using the inherited current canonical master."""
import base64,json,os,zlib
from tatemono_map.cloud.quality import release
from tatemono_map.cloud.storage import GCSStore
result=release(GCSStore(os.environ['GCP_BUCKET']),'work/quality',os.environ['QUALITY_SOURCE_COMMIT'],1792811980879908,commit=os.environ['QUALITY_MODE']=='commit')
encoded=base64.b64encode(zlib.compress(json.dumps(result,ensure_ascii=False).encode())).decode()
for i in range(0,len(encoded),8000):print('QUALITY_AUDIT_CHUNK='+str(i//8000)+':'+encoded[i:i+8000],flush=True)
print('QUALITY_AUDIT_END='+str((len(encoded)+7999)//8000),flush=True)
