#!/usr/bin/env bash
# Run once in authenticated Cloud Shell. Optional IAM-only preparation.
set -euo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")/.."
command -v gcloud >/dev/null
prepare_iam=false
if [ "${1:-}" = '--prepare-iam' ]; then
  prepare_iam=true
  shift
  command -v gh >/dev/null || { echo 'GitHub CLI required for IAM preparation; run read-only audit without --prepare-iam.'; exit 1; }
  gh auth status >/dev/null 2>&1 || { echo 'Authenticate GitHub CLI with gh auth login --web before IAM preparation.'; exit 1; }
fi
mkdir -p work
python3 -m venv work/gcp-setup-venv
work/gcp-setup-venv/bin/python -m pip install --quiet -e . -r requirements-cloud.txt
args=(--root "$PWD/data" --root "$PWD/backups" --root "$PWD/tmp/backups" --root "$PWD/work/initial-input")
if [ -d "$HOME/tatemono-cloud-poc" ]; then
  args+=(--root "$HOME/tatemono-cloud-poc")
fi
for item in buildings_master building_key_aliases; do
  if [ -f "work/initial-input/$item.csv" ]; then
    case "$item" in
      buildings_master) args+=(--canonical-csv "work/initial-input/$item.csv");;
      building_key_aliases) args+=(--aliases-csv "work/initial-input/$item.csv");;
    esac
  fi
done
PYTHONPATH=src work/gcp-setup-venv/bin/python cloud/preflight_gcp.py "${args[@]}" "$@"
if [ "$prepare_iam" = true ]; then
  if [ ! -f work/setup.private.json ]; then
    cp cloud/setup.example.json work/setup.private.json
  fi
  # Setup independently verifies the handoff's existing resources and refuses
  # mismatches. It cannot create/rebuild a bucket, Job or registry.
  PYTHONPATH=src work/gcp-setup-venv/bin/python cloud/setup_gcp.py --config work/setup.private.json --apply
fi
echo 'Private report: work/first-connect/report.private.json. Do not publish candidates or report to GitHub.'
