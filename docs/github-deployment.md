# Manual development deployments from GitHub

After this one-time setup, open **Actions → Deploy development → Run workflow**,
leave the branch as **main**, and run it. There is no deployment on push or PR.
The workflow becomes visible after its PR is merged into the default branch.

It deploys the exact `main` commit selected when the run starts. It waits up to ten
minutes for that commit's existing **CI** push run to pass; missing, failed or
cancelled CI never authorizes deployment. It then connects to `deploy@2.31.42.230`
and runs the existing backup/build/migration/health-check procedure, including
Mailpit and the analysis worker. The job summary records the deployed commit.
No application passwords or database credentials need to leave the server.

## 1. Install the server command once, after merging

In your existing operator SSH session, as `deploy`:

```bash
cd ~/scientific-dataset-copilot
git switch main
git pull --ff-only
install -d -m 0755 ~/.local/bin
install -m 0755 deploy/development/ssh-deploy.sh ~/.local/bin/sdc-deploy
```

This installed copy must live **outside** the Git checkout so updating the
checkout cannot modify a script while Bash is reading it. If a later PR changes
`ssh-deploy.sh`, review it and repeat the final `install` command. Normal app
deployments do not require this step again.

The checkout must stay on `main`, with no tracked edits or untracked files.
Ignored `.env.development`, tester secrets, backups and artifacts are preserved.
Keep the existing server-to-GitHub read-only deploy key and SSH alias; the server
continues using them for `git fetch`. The helper never uses `git reset --hard`.

## 2. Create a separate Actions-to-server SSH key

On your Windows PC, in PowerShell:

```powershell
$sdcActionsKey = "$env:USERPROFILE\.ssh\sdc-github-actions"
if (-not (Test-Path $sdcActionsKey)) {
    ssh-keygen -t ed25519 -C "sdc-github-actions" -f $sdcActionsKey
}
Get-Content "$sdcActionsKey.pub"
```

For this dedicated automation key, press Enter twice at the passphrase prompts
to leave it empty. Keep your existing interactive operator key and its passphrase.
Copy only the printed public key for the next command.

In the server's operator SSH session:

```bash
install -d -m 0700 ~/.ssh
touch ~/.ssh/authorized_keys
chmod 0600 ~/.ssh/authorized_keys
read -r -p 'Paste the Actions public key: ' actions_key
ssh-keygen -lf <(printf '%s\n' "$actions_key") && \
  printf 'restrict,command="%s/.local/bin/sdc-deploy" %s\n' "$HOME" "$actions_key" >> ~/.ssh/authorized_keys
unset actions_key
```

Run that append once. `restrict` disables PTY, forwarding and user rc execution;
the forced command accepts only `deploy <full lowercase commit SHA>`. It verifies
the commit is on `origin/main`, allows only a forward update or repeat deployment,
and holds the same lock as `deploy.sh` throughout Git update and deployment.
Keep the existing operator key line: it is needed for maintenance and Mailpit.

Check the restriction from PowerShell while SSH is still limited to your home IP:

```powershell
ssh -i "$env:USERPROFILE\.ssh\sdc-github-actions" -o IdentitiesOnly=yes deploy@2.31.42.230 whoami
```

Expected: `Only "deploy <full lowercase commit SHA>" is allowed.` and a nonzero
exit. If a username or shell appears, fix the `authorized_keys` line before using
the key in Actions. This check does not deploy anything.

## 3. Pin the server host key

In your already verified operator SSH session (or the Hetzner console), run:

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
awk '{print "2.31.42.230 " $1 " " $2}' /etc/ssh/ssh_host_ed25519_key.pub
```

The second command prints a `known_hosts` line beginning with
`2.31.42.230 ssh-ed25519`. Save that full line for GitHub below. Use this trusted
channel, not an unverified `ssh-keyscan` from the runner. If the server is rebuilt,
verify its new fingerprint in Hetzner before replacing this value.

## 4. Create the GitHub environment and two secrets

Open this repository's **Settings → Environments → New environment**, name it
**development**, and configure **Deployment branches and tags → Selected branches
and tags** with a **branch** rule for **main** only. Do not add a tag rule.
Required reviewers are optional; leaving them empty retains a single manual run
button. Keep deployment credentials in this environment, not repository secrets.

Add these **environment secrets**:

| Name | Value |
| --- | --- |
| `DEVELOPMENT_SSH_KEY` | Entire private key from `sdc-github-actions`, including BEGIN/END lines |
| `DEVELOPMENT_KNOWN_HOSTS` | Full `2.31.42.230 ssh-ed25519 ...` line from step 3 |

To copy the private key directly to your Windows clipboard:

```powershell
Get-Content -Raw "$env:USERPROFILE\.ssh\sdc-github-actions" | Set-Clipboard
```

Paste it into the secret value in GitHub. Do not paste it into chat, commit it, or
reuse the operator key or server-to-GitHub key. Clear the clipboard afterwards:

```powershell
Set-Clipboard -Value ''
```

No PAT, Hetzner API token, tester password, or extra GitHub variables are needed.
The workflow uses the temporary read-only `GITHUB_TOKEN` to inspect CI. Its SSH
private key file is created with restricted permissions and removed on step exit.

## 5. Allow the hosted runner to reach SSH

The original firewall permits TCP 22 only from your home IPv4 `/32`. Standard
GitHub-hosted runners have changing outbound IPs, so that rule blocks this job.
For this setup, **change the Hetzner inbound TCP 22 source to `0.0.0.0/0`**.
This makes the SSH port reachable from the Internet; authentication still requires
an authorized key. Before changing the rule, verify the effective SSH settings:

```bash
sudo sshd -T | grep -E '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin) '
```

All three values must be `no`, as configured in the initial deployment guide.
If they are not, finish that guide's SSH hardening before changing the firewall.
Keep TCP 80/443 as configured and keep the database, API, SMTP and Mailpit ports
closed. The workflow connects over IPv4, so it needs no new IPv6 SSH rule. If UFW
or another host firewall is active, its SSH rule must also allow the runner.

If Internet-reachable SSH is unsuitable, retain the home-IP restriction and use
a runner with static egress or a private network connection before enabling this
workflow. The workflow does not change firewall rules or install a persistent
runner on the application server. Do not copy all GitHub runner IP ranges into
the firewall: GitHub recommends against that large, changing allowlist.

## 6. Run and verify

1. Merge the workflow PR and wait for **CI** on `main` (not just the PR) to pass.
2. Open **Actions → Deploy development → Run workflow**, select **main**, and run.
3. Open the run's **Deploy over pinned-host SSH** logs. Success includes
   `Development deployment completed for commit ...` and healthy containers.
4. Open <https://scientific-dataset-copilot.duckdns.org>, sign in, and test **Your
   analyses**. Keep using the existing operator key for the Mailpit tunnel.

Repeated runs of the same commit are supported and create another database backup.
Existing accounts, tester credentials, database and analysis artifacts are retained.
One deployment runs at a time. GitHub may replace an older *pending* deployment
with a newer one; it does not cancel the active run. The server lock also rejects
overlap with an operator's `deploy.sh`. An old queued run cannot downgrade a newer
server checkout. If `main` advances while a run waits, the run still deploys its
original checked commit, provided the server has not moved past it.

## Failures and recovery

| Message or symptom | Next action |
| --- | --- |
| CI missing, failed, cancelled, or timed out | Inspect the linked CI run; fix/rerun CI, then start a new deployment. No server update has run. |
| SSH connection timeout | Check the Hetzner and host firewalls and server availability. |
| Host key verification failed | Verify the fingerprint in Hetzner, then update `DEVELOPMENT_KNOWN_HOSTS`. |
| Permission denied (publickey) | Check the dedicated public key's forced-command line and matching environment private key. |
| Checkout has local changes / is not on main | Inspect `git status` on the server and resolve the changes deliberately. |
| Already running / would move backwards | Let the active deployment finish; run a new workflow from current `main`. |
| Image build or gateway validation failed | Inspect the stage error. The running app has not yet been stopped. Fix and rerun. |
| Migration or startup failed | Inspect the deployment logs and Compose status through operator SSH before retrying. |

Avoid cancelling during the database migration or restart. A cancelled job, SSH
disconnect, or timeout is not proof the server stopped immediately or completed;
inspect `bash deploy/development/compose.sh ps` and logs through operator SSH.
The server lock prevents another deployment while the previous process holds it.
There is no automatic database downgrade or volume deletion. Recovery guidance and
backup locations are in [the server guide](development-deployment.md#6-updates-recovery-and-operational-boundaries).

The existing manual operator deployment remains available. Do not run `git pull`
concurrently with an Actions deployment. To use the same locked update path from
the server, choose a reviewed full `main` SHA and run:

```bash
SSH_ORIGINAL_COMMAND='deploy FULL_40_CHARACTER_COMMIT_SHA' ~/.local/bin/sdc-deploy
```

The local helper enforces the branch and update rules; the CI gate is enforced by
the GitHub workflow. Rotate or revoke the automation key by removing its
`sdc-github-actions` line from `authorized_keys` and replacing/deleting the GitHub
secret. Changes to the server address, account or repository location require a
reviewed update to the workflow and installed helper.

References: [Manual workflow runs](https://docs.github.com/actions/managing-workflow-runs/manually-running-a-workflow),
[deployment environments](https://docs.github.com/actions/deployment/about-deployments/deploying-with-github-actions),
[hosted runner IP ranges](https://docs.github.com/en/actions/reference/runners/github-hosted-runners),
[OpenSSH authorized keys](https://man.openbsd.org/sshd#AUTHORIZED_KEYS_FILE_FORMAT).
