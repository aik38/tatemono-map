# Cleanup inventory (safe isolate-first)

## Scope and guardrails
- Canonical source remains SQLite `buildings` table.
- `canonical_name`/`canonical_address` auto-overwrite behavior unchanged.
- Must-keep scripts/pipelines were not moved/deleted.

## Candidate discovery commands (exact)
```bash
rg --files | rg -n 'buildings_master|merge_building_masters|rebuild_dist|legacy|mvp_v1|_OLD_'
rg -n 'buildings_master|merge_building_masters|rebuild_dist|mvp_v1|_OLD_' README.md docs scripts src tests
```

### Initial discovery notes
- Initial suspect family found: legacy `buildings_master` module and test coverage around that flow.
- No `merge_building_masters`, `rebuild_dist`, `mvp_v1`, `_OLD_` files found.

## Classified candidates
| Candidate | Classification | Size (bytes) | Last modified (UTC) | Reference check command | Current references |
|---|---|---:|---|---|---|
| `src/tatemono_map/legacy/master_rebuild/from_sources.py` | Legacy module (isolated, kept for compatibility helper functions) | 18404 | 2026-02-22 05:26:16 | `rg -n 'legacy\.master_rebuild|master_rebuild' src scripts tests docs README.md` | Referenced by `src/tatemono_map/building_registry/normalization.py` and legacy test |
| `src/tatemono_map/legacy/master_rebuild/__init__.py` | Legacy module package marker | 201 | 2026-02-22 05:26:06 | same as above | No active workflow entrypoint dependency |
| `tests/legacy/test_legacy_master_rebuild_from_sources.py` | Legacy test (moved from active tests root) | 3017 | 2026-02-22 05:26:33 | same as above | Self-contained legacy test |

Metadata command used:
```bash
stat -c '%n|%s|%y' src/tatemono_map/legacy/master_rebuild/from_sources.py src/tatemono_map/legacy/master_rebuild/__init__.py tests/legacy/test_legacy_master_rebuild_from_sources.py
```

## Isolation actions
- `git mv src/tatemono_map/buildings_master src/tatemono_map/legacy/master_rebuild`
- `git mv tests/test_buildings_master_from_sources.py tests/legacy/test_legacy_master_rebuild_from_sources.py`
- Added DEPRECATED headers to moved legacy module/test files.
- Added `docs/legacy/README.md` and `scripts/legacy/README.md` as reference-only placeholders.

## Required reference checks after isolation

### A) README/docs must not reference legacy paths/tokens
Command:
```bash
rg -n "scripts/legacy|docs/legacy|buildings_master|merge_building_masters|rebuild_dist" README.md docs
```
Output:
```text
(no matches)
```

### B) Active scripts/src must not call isolated legacy scripts
Command:
```bash
rg -n "scripts/legacy|buildings_master|merge_building_masters|rebuild_dist" scripts src/tatemono_map
```
Output:
```text
(no matches)
```

### C) Critical entrypoints still exist (PowerShell Test-Path equivalent)
PowerShell command attempted:
```bash
pwsh -NoProfile -Command '$paths = @("scripts/run_pdf_zip_latest.ps1", ... ); foreach ($p in $paths) { Write-Output ("$p`t$([bool](Test-Path $p))") }'
```
Result:
```text
pwsh is not available in this container (bash: command not found: pwsh)
```
Fallback equivalent command used:
```bash
python - <<'PY'
from pathlib import Path
paths = [
  'scripts/run_pdf_zip_latest.ps1','scripts/run_pdf_zip.ps1','scripts/run_pdf_batch_pipeline.ps1',
  'scripts/weekly_update.ps1','scripts/publish_public.ps1','scripts/run_ulucks_manual_pdf.ps1',
  'scripts/run_ulucks_smartlink.ps1','src/tatemono_map/cli/pdf_batch_run.py',
  'src/tatemono_map/building_registry/normalization.py','src/tatemono_map/building_registry/matcher.py',
  'src/tatemono_map/building_registry/seed_from_ui.py','src/tatemono_map/building_registry/ingest_master_import.py',
  'src/tatemono_map/normalize/building_summaries.py','docs/spec.md','docs/runbook.md','docs/data_contract.md',
  'docs/wbs.md','docs/README.md','tests/test_building_registry.py'
]
for p in paths:
    print(f"{p}\t{Path(p).exists()}")
PY
```
Output:
```text
scripts/run_pdf_zip_latest.ps1	True
scripts/run_pdf_zip.ps1	True
scripts/run_pdf_batch_pipeline.ps1	True
scripts/weekly_update.ps1	True
scripts/publish_public.ps1	True
scripts/run_ulucks_manual_pdf.ps1	True
scripts/run_ulucks_smartlink.ps1	True
src/tatemono_map/cli/pdf_batch_run.py	True
src/tatemono_map/building_registry/normalization.py	True
src/tatemono_map/building_registry/matcher.py	True
src/tatemono_map/building_registry/seed_from_ui.py	True
src/tatemono_map/building_registry/ingest_master_import.py	True
src/tatemono_map/normalize/building_summaries.py	True
docs/spec.md	True
docs/runbook.md	True
docs/data_contract.md	True
docs/wbs.md	True
docs/README.md	True
tests/test_building_registry.py	True
```

## Smoke tests
1) Canonical test (environment-equivalent to requested Windows command):
```bash
PYTHONPATH=src python -m pytest -q tests/test_building_registry.py
```
Output:
```text
...                                                                      [100%]
3 passed in 0.19s
```

2) PDF CLI import smoke:
```bash
PYTHONPATH=src python -m tatemono_map.cli.pdf_batch_run -h
```
Output:
```text
ModuleNotFoundError: No module named 'pandas'
```
Status: environment dependency missing, not caused by cleanup changes.

3) Optional weekly_update dry run:
- Not executed because PowerShell (`pwsh`) is unavailable in this container.

## Deletion decision
- No deletion commit performed.
- Rationale: isolate-first completed; environment limitations prevented full Windows/PowerShell smoke parity. Keeping all legacy-isolated artifacts is safer.
