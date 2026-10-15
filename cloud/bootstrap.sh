#!/usr/bin/env bash
# One initial Cloud Shell entrypoint. All setup inputs remain under ignored work/.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
command -v gcloud >/dev/null
command -v gh >/dev/null
python3 -m venv work/gcp-setup-venv
work/gcp-setup-venv/bin/python -m pip install --no-cache-dir -e . -r requirements-cloud.txt
PYTHONPATH=src work/gcp-setup-venv/bin/python cloud/setup_gcp.py "$@"
