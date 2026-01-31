Continue = "Stop"
 = Split-Path -Parent 
Set-Location 
. .\.venv\Scripts\Activate.ps1
python -m tatemono_map.ingest.run
