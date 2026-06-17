#!/bin/bash
set -e

# Download validator JAR from GCS if it's a Git LFS pointer or missing
python /app/scripts/fetch_validator_jar.py || echo "WARNING: validator JAR fetch failed — /validate endpoint will not work"

exec "$@"
