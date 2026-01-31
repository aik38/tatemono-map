Continue = "Stop"
 = Split-Path -Parent 
Set-Location 
if (-not (Test-Path .\.venv)) {
  python -m venv .venv
}
. .\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
pip install -e .
Write-Host "OK: dev setup complete"
