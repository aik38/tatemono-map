"""The one-shot operator entrypoint must stop before writes on changed inputs."""
import json
import os
import subprocess

import pytest
from test_setup import ROOT


@pytest.mark.parametrize('dirty,expected_reason', [(True,'tracked_changes_preserved_no_checkout'),(False,'latest_main_differs_from_reviewed_sha')])
def test_operator_entrypoint_preserves_checkout_when_review_is_stale(tmp_path, dirty, expected_reason):
    checkout=tmp_path/'existing';checkout.mkdir()
    tools=tmp_path/'bin';tools.mkdir()
    calls=tmp_path/'calls'
    git=tools/'git'
    git.write_text('''#!/usr/bin/env python3
import json,os,sys
with open(os.environ['TEST_CALLS'],'a') as f:f.write(json.dumps(sys.argv[1:])+'\\n')
args=sys.argv[1:]
if args[:2]==['status','--porcelain']:print(' M existing.py' if os.environ['TEST_DIRTY']=='true' else '')
elif args[:2]==['config','--get']:print('https://github.com/aik38/tatemono-map.git')
elif args==['rev-parse','origin/main']:print('b'*40)
elif args[:1]!=['fetch']:sys.exit(42)
''')
    git.chmod(0o755)
    result=subprocess.run(['bash',str(ROOT/'cloud/complete_initial_release.sh'),'a'*40,str(checkout)],capture_output=True,text=True,env={**os.environ,'PATH':str(tools)+':'+os.environ['PATH'],'TEST_CALLS':str(calls),'TEST_DIRTY':str(dirty).lower()})
    assert result.returncode==1
    diagnostic=json.loads((checkout/'work/initial-release/handoff.private.json').read_text())
    assert diagnostic['reason']==expected_reason
    assert diagnostic['production_verified'] is False
    assert not any(json.loads(line)[0] in ('checkout','branch') for line in calls.read_text().splitlines())
