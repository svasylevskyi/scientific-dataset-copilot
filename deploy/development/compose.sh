#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
exec docker compose --project-directory "$repo_root" \
  --env-file "$repo_root/.env.development" \
  -f "$repo_root/compose.development.yaml" "$@"
