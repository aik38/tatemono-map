from datetime import datetime, timezone

from tatemono_map.cloud.realpro_weekly import monday_start, upstream_status, integrate


def test_week_boundary_is_monday_four_jst():
    date = datetime(2026, 10, 25, 19, 5, tzinfo=timezone.utc)
    assert monday_start(date).isoformat() == '2026-10-26T04:00:00+09:00'


def test_failed_ulucks_is_finished_and_does_not_block_realpro():
    since = monday_start(datetime(2026, 10, 26, 0, tzinfo=timezone.utc))
    execution = {'createTime': '2026-10-25T19:00:00Z', 'completionTime': '2026-10-25T20:15:00Z',
                 'conditions': [{'type': 'Completed', 'state': 'CONDITION_FAILED'}]}
    assert upstream_status([execution], since) == 'finished'


def test_an_older_live_execution_blocks_even_after_a_newer_execution_finished():
    since = monday_start(datetime(2026, 10, 26, 0, tzinfo=timezone.utc))
    executions = [{'createTime': '2026-10-25T18:58:00Z'},
                  {'createTime': '2026-10-25T19:00:00Z', 'completionTime': '2026-10-25T20:00:00Z'}]
    assert upstream_status(executions, since) == 'running'


def test_last_week_success_is_not_this_weeks_execution():
    since = monday_start(datetime(2026, 10, 26, 0, tzinfo=timezone.utc))
    execution = {'createTime': '2026-10-18T19:00:00Z', 'completionTime': '2026-10-18T21:40:00Z'}
    assert upstream_status([execution], since) == 'not_started'


def test_duplicate_only_does_not_commit_or_change_head(monkeypatch, tmp_path):
    from contextlib import nullcontext
    from tatemono_map.cloud import realpro_batch, realpro_weekly
    head = {'run_id': 'current'}
    monkeypatch.setattr(realpro_batch, 'backup_current', lambda *a: (head, 123, {}))
    report = {'parsed_rows': 10, 'row_counts': {'duplicate': 10}, 'counts_before': {},
              'counts_after': {}, 'public_counts': {}, 'pdf_count': 2, 'pdf_pages': 3,
              'attached_rows': 0}
    monkeypatch.setattr(realpro_batch, 'update_batch', lambda *a: dict(report))
    monkeypatch.setattr(realpro_batch, 'preserve_ulucks_catalog', lambda *a: None)
    monkeypatch.setattr(realpro_weekly, 'save_json', lambda *a: {})
    def forbidden(*a, **kw): raise AssertionError('duplicate input must never commit a release')
    monkeypatch.setattr(realpro_weekly, 'commit_release', forbidden)
    class Store:
        def collection_lease(self, owner): return nullcontext()
    result = integrate(Store(), [], tmp_path, 'run', 'commit', {}, 2)
    assert result['status'] == 'no_new_content'
    assert result['head'] is head
