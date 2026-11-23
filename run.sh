#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip --isolated install --index-url https://pypi.org/simple --disable-pip-version-check -r requirements.txt
exec .venv/bin/python -m uvicorn bank_agent.web:app --host 127.0.0.1 --port 8000
