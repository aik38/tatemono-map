$ErrorActionPreference = "Stop"

Write-Host "========================================"
Write-Host "Canonical Registry Weekly Update"
Write-Host "========================================"
Write-Host "NOTE: Close data/public/public.sqlite3 in DB Browser or other tools before running to avoid lock errors."
Write-Host ""

Write-Host "[STEP 1/4] run_pdf_zip_latest"
pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "run_pdf_zip_latest.ps1")

Write-Host "[STEP 2/4] ingest_master_import"
pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "ingest_master_import.ps1")

Write-Host "[STEP 3/4] publish_public"
pwsh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "publish_public.ps1")

Write-Host "[STEP 4/4] render static site (--version all)"
python -m tatemono_map.render.build --db-path data/public/public.sqlite3 --output-dir dist --version all

Write-Host ""
Write-Host "[DONE] Canonical weekly update completed."
