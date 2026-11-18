#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
: "${DELTA_JWT_SECRET:?Export a random JWT secret of at least 32 characters}"
exec .venv/bin/python -m uvicorn delta_demo.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
