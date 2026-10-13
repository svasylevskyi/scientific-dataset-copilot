#!/usr/bin/env bash
# Run from an already checked-out, reviewed commit. Updating Git is explicit.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
exec 9>"$repo_root/.development-deploy.lock"
flock -n 9 || { echo 'A development deployment is already running.' >&2; exit 1; }
compose=(bash deploy/development/compose.sh)
"${compose[@]}" config --quiet
"${compose[@]}" build api migrate web
"${compose[@]}" run --rm --no-deps web caddy validate --config /etc/caddy/Caddyfile
"${compose[@]}" up -d --wait db mailpit
# Back up the old database before any migration, including repeat deployments.
umask 077
mkdir -p backups/development
backup="backups/development/$(date -u +%Y%m%dT%H%M%SZ)-$(git rev-parse --short HEAD).dump"
"${compose[@]}" exec -T db pg_dump -U sdc -d sdc -Fc > "${backup}.partial"
mv -- "${backup}.partial" "$backup"
# Brief maintenance window prevents older API code from running against a changing schema.
"${compose[@]}" stop web api
"${compose[@]}" run --rm migrate
"${compose[@]}" up -d --wait api web
"${compose[@]}" ps
printf 'Development deployment completed for commit %s.\n' "$(git rev-parse HEAD)"
