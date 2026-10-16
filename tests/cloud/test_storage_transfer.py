"""Transfer settings and lost-response reconciliation against immutable objects."""
import hashlib
from pathlib import Path

import pytest
from google.api_core.exceptions import NotFound, PreconditionFailed
from requests.exceptions import ConnectionError

from tatemono_map.cloud.collector import CollectionError
from tatemono_map.cloud.storage import GCSStore, UPLOAD_CHUNK_BYTES, TRANSFER_TIMEOUT


class Bucket:
    name = 'private-test-bucket'
    def __init__(self):
        self.objects = {}
        self.calls = []
        self.lose_response = False
        self.fail_before_write = False
    def blob(self, name, **options):
        bucket = self
        class Blob:
            generation = None
            size = None
            def reload(self, **kw):
                if name not in bucket.objects: raise NotFound('missing')
                self.generation, data = bucket.objects[name]
                self.size = len(data)
            def download_to_filename(self, output, **kw):
                generation, data = bucket.objects[name]
                assert kw['if_generation_match'] == options['generation']
                if generation != kw['if_generation_match']: raise PreconditionFailed('changed')
                Path(output).write_bytes(data)
            def upload_from_filename(self, path, **kw):
                bucket.calls.append((options,kw))
                assert kw['if_generation_match'] == 0
                if name in bucket.objects: raise PreconditionFailed('exists')
                if bucket.fail_before_write: raise ConnectionError('write timed out')
                self.generation = len(bucket.objects) + 1
                bucket.objects[name] = (self.generation,Path(path).read_bytes())
                if bucket.lose_response: raise ConnectionError('acknowledgement lost')
        return Blob()


def store():
    result = object.__new__(GCSStore)
    result.bucket = Bucket()
    return result


def test_small_chunks_and_conditional_retry_without_weakening_create_only(tmp_path):
    cloud=store();path=tmp_path/'master';path.write_bytes(b'private-data')
    ref=cloud.upload(path,'masters/a')
    options,kwargs=cloud.bucket.calls[0]
    assert options['chunk_size']==UPLOAD_CHUNK_BYTES==8*1024*1024
    assert kwargs['timeout']==TRANSFER_TIMEOUT==(20,180)
    assert kwargs['checksum']=='crc32c'
    assert kwargs['retry'].get_retry_policy_if_conditions_met(query_params={'ifGenerationMatch':0}) is not None
    assert kwargs['retry'].get_retry_policy_if_conditions_met(query_params={}) is None
    assert ref['sha256']==hashlib.sha256(b'private-data').hexdigest()


def test_lost_final_upload_response_reuses_only_identical_stored_bytes(tmp_path):
    cloud=store();cloud.bucket.lose_response=True
    path=tmp_path/'master';path.write_bytes(b'private-data')
    first=cloud.upload_verified(path,'masters/a')
    assert cloud.upload_verified(path,'masters/a')==first
    assert len(cloud.bucket.calls)==1
    assert len(cloud.bucket.objects)==1


def test_incomplete_transfer_remains_retryable_without_fabricating_a_reference(tmp_path):
    cloud=store();cloud.bucket.fail_before_write=True
    path=tmp_path/'master';path.write_bytes(b'private-data')
    with pytest.raises(ConnectionError):cloud.upload_verified(path,'masters/a')
    assert cloud.bucket.objects=={}
    cloud.bucket.fail_before_write=False
    assert cloud.upload_verified(path,'masters/a')['generation']==1


def test_existing_same_length_different_content_is_never_overwritten(tmp_path):
    cloud=store();cloud.bucket.objects['masters/a']=(9,b'wrong-content')
    path=tmp_path/'master';path.write_bytes(b'right-content')
    with pytest.raises(CollectionError,match='checksum_mismatch'):
        cloud.upload_verified(path,'masters/a')
    assert cloud.bucket.objects['masters/a']==(9,b'wrong-content')
    assert not cloud.bucket.calls


def test_real_storage_sdk_sends_large_file_in_eight_mib_chunks(tmp_path):
    import base64,json,threading
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    import google_crc32c
    from google.auth.credentials import AnonymousCredentials
    from google.cloud.storage import Client
    payload=b'a'*(9*1024*1024)
    chunks=[];received=bytearray()
    class Handler(BaseHTTPRequestHandler):
        def send(self,status,data=b'',**headers):
            self.send_response(status)
            self.send_header('Content-Length',str(len(data)))
            for k,v in headers.items():self.send_header(k,v)
            self.end_headers();self.wfile.write(data)
        def do_POST(self):
            assert 'ifGenerationMatch=0' in self.path
            self.rfile.read(int(self.headers['Content-Length']))
            self.send(200,Location=f'http://127.0.0.1:{self.server.server_port}/session')
        def do_PUT(self):
            data=self.rfile.read(int(self.headers['Content-Length']))
            chunks.append(len(data));received.extend(data)
            if len(received)<len(payload):
                self.send(308,Range=f'bytes=0-{len(received)-1}')
            else:
                metadata={'name':'masters/test.sqlite3','bucket':'test','generation':'7','size':str(len(payload)),'crc32c':base64.b64encode(google_crc32c.value(payload).to_bytes(4,'big')).decode()}
                self.send(200,json.dumps(metadata).encode(),**{'Content-Type':'application/json'})
        def log_message(self,*a):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        path=tmp_path/'master';path.write_bytes(payload)
        client=Client(project='test',credentials=AnonymousCredentials(),client_options={'api_endpoint':f'http://127.0.0.1:{server.server_port}'})
        ref=GCSStore('test',client=client).upload(path,'masters/test.sqlite3')
        assert ref['generation']==7
        assert chunks==[8*1024*1024,1024*1024]
        assert bytes(received)==payload
    finally:
        server.shutdown();server.server_close();thread.join()
