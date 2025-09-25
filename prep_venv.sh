#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Recreate venv with real files (no symlinks)
rm -rf venv
python3 -m venv --copies venv

source venv/bin/activate
pip install -r requirements.txt
python - <<'PY'
import sys, platform, streamlit
print("PY OK:", sys.version, platform.platform(), "streamlit", streamlit.__version__)
PY
deactivate

# Dereference any leftover links (safety)
rsync -aL venv/ venv_real/
rm -rf venv
mv venv_real venv

# Sanity checks
test -x venv/bin/python3.12 || { echo "ERROR: python3.12 missing"; exit 2; }
test "$(find venv -type l | wc -l | tr -d ' ')" = "0" || { echo "ERROR: symlinks remain"; exit 3; }