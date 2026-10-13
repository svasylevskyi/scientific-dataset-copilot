#!/usr/bin/env bash
# Run from an already checked-out, reviewed commit. Updating Git is explicit.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
exec 9>"$repo_root/.development-deploy.lock"
flock -n 9 || { echo 'A development deployment is already running.' >&2; exit 1; }
export SDC_SOURCE_REVISION="$(git rev-parse HEAD)"
compose=(bash deploy/development/compose.sh)
stage='configuration checks'
trap 'status=$?; printf "Development deployment failed during %s (exit %s). The update is not complete.\n" "$stage" "$status" >&2; exit "$status"' ERR
"${compose[@]}" config --quiet
stage='image build'
"${compose[@]}" build api migrate worker web
stage='gateway validation (before stopping the current app)'
"${compose[@]}" run --rm --no-deps --pull never web-validate
stage='database and mail startup'
"${compose[@]}" up -d --wait db mailpit
# Back up the old database before any migration, including repeat deployments.
stage='database backup'
umask 077
mkdir -p backups/development
backup="backups/development/$(date -u +%Y%m%dT%H%M%SZ)-$(git rev-parse --short HEAD).dump"
"${compose[@]}" exec -T db pg_dump -U sdc -d sdc -Fc > "${backup}.partial"
mv -- "${backup}.partial" "$backup"
# Brief maintenance window prevents older API code from running against a changing schema.
stage='application shutdown'
"${compose[@]}" stop web api worker
stage='database migration'
"${compose[@]}" run --rm migrate
stage='application startup'
"${compose[@]}" up -d --wait api worker web
"${compose[@]}" ps
printf 'Development deployment completed for commit %s.\n' "$(git rev-parse HEAD)"
