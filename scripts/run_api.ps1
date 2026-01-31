Continue = "Stop"
 = Split-Path -Parent 
Set-Location 
. .\.venv\Scripts\Activate.ps1
uvicorn tatemono_map.api.main:app --reload
