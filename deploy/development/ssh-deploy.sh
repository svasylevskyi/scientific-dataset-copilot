#!/usr/bin/env bash
# Install a reviewed copy outside the checkout as ~/.local/bin/sdc-deploy.
# The dedicated Actions SSH key must force this command (see the setup guide).
set -euo pipefail
if [[ ! ${SSH_ORIGINAL_COMMAND:-} =~ ^deploy\ ([0-9a-f]{40})$ ]]; then
  echo 'Only "deploy <full lowercase commit SHA>" is allowed.' >&2
  exit 1
fi
revision="${BASH_REMATCH[1]}"
repo_root="$HOME/scientific-dataset-copilot"
cd "$repo_root"
exec 9>"$repo_root/.development-deploy.lock"
flock -n 9 || { echo 'A development deployment is already running.' >&2; exit 1; }

[[ "$(git branch --show-current)" == main ]] || {
  echo 'The server checkout must be on main.' >&2; exit 1;
}
[[ -z "$(git status --porcelain --untracked-files=normal)" ]] || {
  echo 'The server checkout has local changes. Resolve them before deploying.' >&2; exit 1;
}
export GIT_TERMINAL_PROMPT=0
export GIT_SSH_COMMAND='ssh -o BatchMode=yes -o StrictHostKeyChecking=yes'
git fetch --no-tags origin +refs/heads/main:refs/remotes/origin/main
git cat-file -e "$revision^{commit}"
git merge-base --is-ancestor "$revision" refs/remotes/origin/main || {
  echo 'The requested commit is not on origin/main.' >&2; exit 1;
}
git merge-base --is-ancestor HEAD "$revision" || {
  echo 'Deployment would move the server backwards or discard local commits. Recovery is manual.' >&2; exit 1;
}
git merge --ff-only --no-edit "$revision"
[[ "$(git rev-parse HEAD)" == "$revision" ]]
printf 'Deploying main commit %s.\n' "$revision"
# FD 9 stays open across exec. deploy.sh reuses it, keeping checkout and deployment
# under the same lock, including against an operator invoking deploy.sh directly.
exec bash deploy/development/deploy.sh
