"""Timing-only regressions; all executions, stores and HTTP responses are synthetic."""
from datetime import datetime
from contextlib import nullcontext
from pathlib import Path
import importlib.util
import subprocess

import pytest
from tatemono_map.cloud import realpro_weekly as realpro, mansion_weekly as mansion

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('now,expected', [
    ('2026-10-29T13:59:59+09:00', '2026-10-22T14:00:00+09:00'),
    ('2026-10-29T14:00:00+09:00', '2026-10-29T14:00:00+09:00'),
    ('2026-10-29T05:00:00+00:00', '2026-10-29T14:00:00+09:00'),
    ('2026-10-30T14:00:00+09:00', '2026-10-29T14:00:00+09:00'),
    ('2026-10-31T23:59:59+09:00', '2026-10-29T14:00:00+09:00'),
    ('2026-11-01T14:00:00+09:00', '2026-10-29T14:00:00+09:00'),
    ('2026-11-02T04:00:00+09:00', '2026-10-29T14:00:00+09:00'),
    ('2026-11-05T13:59:59+09:00', '2026-10-29T14:00:00+09:00'),
    ('2026-11-05T14:00:00+09:00', '2026-11-05T14:00:00+09:00'),
    ('2027-01-01T00:00:00+09:00', '2026-12-31T14:00:00+09:00'),
])
def test_most_recent_thursday_boundary(now, expected):
    assert realpro.weekly_start(datetime.fromisoformat(now)).isoformat() == expected
    assert mansion.weekly_start is realpro.weekly_start


def test_previous_monday_is_not_this_thursday_and_running_still_blocks():
    since = realpro.weekly_start(datetime.fromisoformat('2026-10-29T14:05:00+09:00'))
    monday = {'createTime': '2026-10-25T19:00:00Z', 'completionTime': '2026-10-25T20:00:00Z'}
    thursday = {'createTime': '2026-10-29T05:00:00Z'}
    assert realpro.upstream_status([monday], since) == 'not_started'
    assert realpro.upstream_status([monday, thursday], since) == 'running'
    failed = {**thursday, 'completionTime': '2026-10-29T06:00:00Z',
              'conditions': [{'type': 'Completed', 'state': 'CONDITION_FAILED'}]}
    # Terminal completion is the existing gate contract, never a success claim.
    assert realpro.upstream_status([monday, failed], since) == 'finished'
    assert failed['conditions'][0]['state'] == 'CONDITION_FAILED'


@pytest.mark.parametrize('kind', ['realpro', 'mansion'])
def test_weekly_gate_waits_for_thursday_executions(monkeypatch, kind):
    import google.auth
    import google.auth.transport.requests
    module = realpro if kind == 'realpro' else mansion
    boundary = datetime.fromisoformat('2026-10-29T14:00:00+09:00')
    monkeypatch.setattr(module, 'weekly_start', lambda: boundary)
    sleeps, queries, counts = [], [], {}
    old = {'createTime': '2026-10-25T19:00:00Z', 'completionTime': '2026-10-25T20:00:00Z'}
    live = {'createTime': '2026-10-29T05:00:00Z'}
    class Response:
        status_code = 200
        def __init__(self, executions): self.executions = executions
        def json(self): return {'executions': self.executions}
    class Session:
        def get(self, url, **kwargs):
            queries.append(url)
            counts[url] = counts.get(url, 0) + 1
            n = counts[url]
            return Response([old] if n == 1 else [old, live] if n == 2 else
                            [old, {**live, 'completionTime': '2026-10-29T06:00:00Z'}])
    monkeypatch.setattr(google.auth, 'default', lambda **kw: (object(), 'test'))
    monkeypatch.setattr(google.auth.transport.requests, 'AuthorizedSession', lambda c: Session())
    monkeypatch.setattr(module.time, 'sleep', sleeps.append)
    if kind == 'realpro':
        result = module.wait_for_ulucks('tatemono-map', 'asia-northeast1')
        assert result['week_start'] == boundary.isoformat()
        assert len(queries) == 3
    else:
        result = module.wait_for_upstream('tatemono-map', 'asia-northeast1', weekly=True)
        assert set(result.values()) == {'finished'}
        assert len(queries) == 6
        assert any('/jobs/tatemono-realpro-weekly/' in q for q in queries)
    assert sleeps == [60, 60]


@pytest.mark.parametrize('kind,explicit,expected', [
    ('realpro', None, 'weekly-2026-10-29'),
    ('mansion', None, 'week-20261029'),
    ('realpro', 'weekly-2026-10-26', 'weekly-2026-10-26'),
    ('mansion', 'week-20261026', 'week-20261026'),
    ('realpro', 'proof-20261024', 'proof-20261024'),
])
def test_default_and_explicit_saved_cycles(monkeypatch, kind, explicit, expected):
    module = realpro if kind == 'realpro' else mansion
    monkeypatch.setattr(module, 'weekly_start',
                        lambda: datetime.fromisoformat('2026-10-29T14:00:00+09:00'))
    for key, value in {'TATEMONO_BUCKET': 'synthetic', 'TATEMONO_SOURCE_COMMIT': 'test',
                       'GOOGLE_CLOUD_PROJECT': 'tatemono-map'}.items():
        monkeypatch.setenv(key, value)
    argv = ['weekly', '--weekly']
    if explicit: argv += ['--cycle', explicit]
    monkeypatch.setattr('sys.argv', argv)
    class Store:
        def collection_lease(self, owner): return nullcontext()
    monkeypatch.setattr(module, 'GCSStore', lambda *a: Store())
    captured = []
    def execute(*args, **kwargs):
        captured.append(kwargs['cycle'])
        return {'status': 'no_new_content'}
    monkeypatch.setattr(module, 'execute', execute)
    if kind == 'realpro':
        monkeypatch.setattr(module, 'wait_for_shared_lease', lambda *a: None)
        monkeypatch.setattr(module, 'wait_for_ulucks', lambda *a: None)
        monkeypatch.setattr(module, 'acquisition_lease', lambda *a: nullcontext())
    else:
        monkeypatch.setattr(module, 'wait_for_upstream', lambda *a, **kw: None)
        monkeypatch.setattr(module.signal, 'signal', lambda *a: None)
        monkeypatch.setattr(module.signal, 'alarm', lambda *a: None)
    module.main()
    assert captured == [expected]


def test_current_scheduler_management_contracts():
    for filename, cron in [
        ('enable_scheduler.py', '0 14 * * 4'),
        ('setup_gcp.py', '0 14 * * 4'),
        ('initial_release.py', '0 14 * * 4'),
        ('recover_initial_deployment.py', '0 14 * * 4'),
        ('mansion_operator.py', '10 14 * * 4'),
    ]:
        source = (ROOT/'cloud'/filename).read_text()
        assert cron in source and 'Asia/Tokyo' in source
        assert '0 4 * * 1' not in source
    # RealPro Scheduler is updated in place by the deployment, not recreated.
    assert (ROOT/'docs/runbook.md').read_text().count('木曜14:05') == 1


def test_production_overlay_preserves_unrelated_code():
    spec = importlib.util.spec_from_file_location('weekly_patch', ROOT/'cloud/patch_weekly_schedule.py')
    patch = importlib.util.module_from_spec(spec); spec.loader.exec_module(patch)
    reference = (ROOT/'src/tatemono_map/cloud/realpro_weekly.py').read_text()
    unrelated = '\n\ndef acquisition():\n    return "preserve latest production collector"\n'
    before = patch.OLD_START + unrelated
    after = patch.patched(before, reference)
    assert after.endswith(unrelated)
    assert 'def weekly_start' in after and 'monday_start' not in after
    mr = 'from upstream import monday_start\ncycle = args.cycle or monday_start().date()\n' + unrelated
    assert patch.patched(mr, reference, mansion=True) == mr.replace('monday_start', 'weekly_start')
    with pytest.raises(ValueError, match='unexpected_realpro'):
        patch.patched('unreviewed timing function', reference)

