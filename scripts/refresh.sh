#!/bin/bash
# Fetch filings + prices now and print which sources worked.
set -euo pipefail
cd "$(dirname "$0")/../backend"
source ../.venv/bin/activate
python -m finn.cli refresh "$@"
echo; echo "Source status:"
python -m finn.cli sources
