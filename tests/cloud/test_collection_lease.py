import json
from types import SimpleNamespace
import pytest
from google.api_core.exceptions import PreconditionFailed
from tatemono_map.cloud.storage import GCSStore
from tatemono_map.cloud.collector import CollectionError


def test_live_lease_blocks_duplicate_and_expired_generation_can_be_recovered():
    state={}; counter=[0]
    class Blob:
        def upload_from_string(self,value,**kwargs):
            expected=kwargs['if_generation_match']
            if expected!=(state.get('generation',0)):raise PreconditionFailed('generation')
            counter[0]+=1;self.generation=counter[0];state.update(value=value,generation=self.generation)
        def reload(self):self.generation=state['generation']
        def download_as_bytes(self,**kwargs):
            assert kwargs['if_generation_match']==state['generation']
            return state['value'].encode()
        def delete(self,**kwargs):
            if kwargs['if_generation_match']!=state['generation']:raise PreconditionFailed('generation')
            state.clear()
    store=GCSStore('test',client=SimpleNamespace(bucket=lambda name:SimpleNamespace(blob=lambda path:Blob())))
    with store.collection_lease('first'):
        with pytest.raises(CollectionError,match='collection_lock_held'):
            with store.collection_lease('duplicate'):raise AssertionError('duplicate ran')
        assert json.loads(state['value'])['owner']=='first'
    assert not state
    state.update(value=json.dumps({'expires_at':0}),generation=50)
    with store.collection_lease('recovered'):
        assert json.loads(state['value'])['owner']=='recovered'
    assert not state
