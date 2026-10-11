#!/bin/sh
# Container entrypoint: seed the fictional org on first boot (a no-op once seeded), then serve.
set -e
mkdir -p /data
python -m app.data.seed.seed
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips="*"
