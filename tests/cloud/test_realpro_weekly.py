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
    monkeypatch.setattr(realpro_batch, 'update_batch', lambda *a, **kw: dict(report))
    monkeypatch.setattr(realpro_batch, 'preserve_ulucks_catalog', lambda *a: None)
    monkeypatch.setattr(realpro_weekly, 'save_json', lambda *a: {})
    def forbidden(*a, **kw): raise AssertionError('duplicate input must never commit a release')
    monkeypatch.setattr(realpro_weekly, 'commit_release', forbidden)
    class Store:
        def collection_lease(self, owner): return nullcontext()
    result = integrate(Store(), [], tmp_path, 'run', 'commit', {}, 2)
    assert result['status'] == 'no_new_content'
    assert result['head'] is head


def test_private_fukuoka_change_keeps_existing_public_scope(master, tmp_path):
    from tests.cloud.test_realpro_batch import initialize, item
    from tatemono_map.cloud.realpro_batch import update_batch
    from tatemono_map.cloud.public_db import readonly
    baseline = initialize(master, tmp_path)
    data = [item([dict(building_name='福岡保存マンション', address='福岡市中央区天神9-8-7')])]
    result = update_batch(master, data, tmp_path, 'private-only', baseline, public_preservation_proof=True)
    assert result['attached_rows'] == 1
    assert result['proof']
    with readonly(tmp_path/'public.sqlite3') as c:
        assert c.execute("SELECT COUNT(*) FROM buildings WHERE canonical_name='福岡保存マンション'").fetchone()[0] == 0
    with readonly(master) as c:
        assert c.execute("SELECT COUNT(*) FROM buildings WHERE canonical_name='福岡保存マンション'").fetchone()[0] == 1


def test_download_callbacks_are_compatible_with_playwright_and_removed(tmp_path, monkeypatch):
    from playwright._impl._impl_to_api_mapping import ImplToApiMapping
    from tatemono_map.cloud import realpro
    mapping = ImplToApiMapping()
    class Events:
        def __init__(self): self.handlers = {}
        def on(self, event, handler):
            # This real Playwright operation rejects builtin list.append handlers.
            mapping.wrap_handler(handler)
            self.handlers[event] = handler
        def remove_listener(self, event, handler):
            assert self.handlers.pop(event) is handler
    context = Events()
    class Download:
        def save_as(self, path): path.write_bytes(b'%PDF-' + b'x'*2000)
    class Button:
        def click(self): page.handlers['download'](Download())
    class Page(Events):
        def locator(self, selector): return Button()
    page = Page()
    context.pages = [page]
    monkeypatch.setattr(realpro, 'room_count', lambda path: (2, 1))
    preserved = []
    path, evidence = realpro.acquire(page, context, tmp_path, '15974', on_download=preserved.append)
    assert preserved == [path]
    assert evidence['expected_rows'] == 2 and evidence['pdf_pages'] == 1
    assert not page.handlers and not context.handlers
