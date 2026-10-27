"""Patch only weekly timing in an inspected, digest-pinned production image."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path

OLD_START = """def monday_start(now=None):
    current = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('Asia/Tokyo'))
    return (current - timedelta(days=current.weekday())).replace(hour=4, minute=0, second=0, microsecond=0)"""


def patched(source, reference, *, mansion=False):
    if mansion:
        if 'monday_start' not in source:
            raise ValueError('unexpected_mansion_weekly_timing')
        result = source.replace('monday_start', 'weekly_start')
    else:
        if source.count(OLD_START) != 1:
            raise ValueError('unexpected_realpro_weekly_timing')
        tree = ast.parse(reference)
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'weekly_start')
        function = ast.get_source_segment(reference, node)
        result = source.replace(OLD_START, function).replace('monday_start', 'weekly_start')
        result = result.replace('Monday 04:00 JST', 'Thursday 14:00 JST')
    ast.parse(result)
    if 'monday_start' in result:
        raise ValueError('old_weekly_timing_remains')
    return result


def main():
    reference = Path('/tmp/weekly-reference.py').read_text()
    for name in ('realpro_weekly', 'mansion_weekly'):
        spec = importlib.util.find_spec('tatemono_map.cloud.' + name)
        if spec is None:
            if name == 'mansion_weekly':
                continue
            raise ValueError('production_weekly_module_missing')
        path = Path(spec.origin)
        before = path.read_text()
        after = patched(before, reference, mansion=name == 'mansion_weekly')
        path.write_text(after)
        print(json.dumps({'module': name, 'before_sha256': hashlib.sha256(before.encode()).hexdigest(),
                          'after_sha256': hashlib.sha256(after.encode()).hexdigest(),
                          'change': 'weekly_timing_only'}), flush=True)
    from datetime import datetime
    from tatemono_map.cloud.realpro_weekly import weekly_start
    assert weekly_start(datetime.fromisoformat('2026-10-29T13:59:59+09:00')).isoformat() == '2026-10-22T14:00:00+09:00'
    assert weekly_start(datetime.fromisoformat('2026-10-29T14:00:00+09:00')).isoformat() == '2026-10-29T14:00:00+09:00'


if __name__ == '__main__':
    main()

