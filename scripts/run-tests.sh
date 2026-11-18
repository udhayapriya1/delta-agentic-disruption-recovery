#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
.venv/bin/python -m pytest tests -q --junitxml=evidence/backend-tests.xml
