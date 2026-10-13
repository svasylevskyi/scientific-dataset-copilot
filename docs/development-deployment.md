# Hetzner development environment

This environment is for private testing of Scientific Dataset Copilot. It has its
own server, database, credentials and email inbox, separate from Research Radar
and any future production environment. Docker Engine and Compose run on Ubuntu;
Docker Desktop is not required on the Windows client.

## 1. Create the server

In the Hetzner project `scientific-dataset-copilot`:

- Name: `sdc-dev-01`.
- Location: Nuremberg; Helsinki is also suitable if capacity is unavailable.
- Type: x86 CX23 (2 vCPU / 4 GB / 40 GB) for current development testing. Check the
  console's availability and total before ordering. CX33 is a larger alternative.
- Image: Ubuntu 24.04 LTS.
- Networking: public IPv4 and IPv6. No additional volume or load balancer needed.
- Authentication: a dedicated SSH public key. Keep its private key on your PC.
- This is disposable test data initially; provider backup configuration is a
  separate choice. The deployment's local dumps do not replace off-server backups.

Create the SSH key in Windows PowerShell if it does not already exist:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
$sdcKey = "$env:USERPROFILE\.ssh\sdc-development"
if (-not (Test-Path $sdcKey)) { ssh-keygen -t ed25519 -C "sdc-development" -f $sdcKey }
Get-Content "$sdcKey.pub"
```

Add the printed `.pub` value to Hetzner and select it during server creation.
Use a passphrase for this interactive operator key.

Attach a Hetzner Cloud Firewall with these inbound rules:

| Protocol/port | Allowed source |
| --- | --- |
| TCP 22 | Your current public IPv4 address with `/32` |
| TCP 80 | Any IPv4 and IPv6 (HTTPS redirect and certificate validation) |
| TCP 443 | Any IPv4 and IPv6 (HTTPS, protected by the tester gate) |

Leave outbound rules empty, which allows outbound traffic. Do not add inbound
rules for 5432, 8000, 5173, 1025 or 8025. Update the SSH source rule if your home IP
changes. Only the app gateway publishes public ports; the database, API and SMTP
have none. Mailpit's HTTP inbox binds to the server's loopback address.

## 2. First login and operator account

Use Hetzner's browser console to inspect the host fingerprint:

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

From Windows, substitute the actual public IPv4:

```powershell
ssh -i "$env:USERPROFILE\.ssh\sdc-development" root@SERVER_IP
```

Compare the first-connection fingerprint with the console. In this root session:

```bash
apt-get update
apt-get upgrade -y
apt-get install -y git ca-certificates curl python3
adduser deploy
usermod -aG sudo deploy
install -d -m 0700 -o deploy -g deploy /home/deploy/.ssh
install -m 0600 -o deploy -g deploy /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
```

Choose a password for the `deploy` user's sudo access. Open another PowerShell
window and verify `ssh -i "$env:USERPROFILE\.ssh\sdc-development" deploy@SERVER_IP`
and `sudo -v` work. Keep the root session open until this succeeds. Then in root:

```bash
cat > /etc/ssh/sshd_config.d/00-sdc-hardening.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sshd -t
systemctl reload ssh
```

Continue subsequent steps as `deploy`.

## 3. Read-only repository access

Create a separate server-to-GitHub deploy key (not your PC's operator key):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/github-sdc-development -C "sdc-development repository read-only"
cat ~/.ssh/github-sdc-development.pub
```

Add this public key under this repository's **Settings → Deploy keys**. Leave
**Allow write access** unchecked. For unattended pulls this narrowly scoped key
can have an empty passphrase; protect its file permissions. In `~/.ssh/config` add:

```sshconfig
Host github-sdc-development
    HostName github.com
    User git
    IdentityFile ~/.ssh/github-sdc-development
    IdentitiesOnly yes
```

Clone the repository. Check GitHub's first-connection fingerprint against its
[official fingerprint list](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints).

```bash
git clone git@github-sdc-development:svasylevskyi/scientific-dataset-copilot.git
cd scientific-dataset-copilot
git switch main
git pull --ff-only
sudo bash deploy/development/install-docker.sh
sudo usermod -aG docker deploy
```

Log out and reconnect so Docker group membership takes effect. Docker access is
administrative host access; grant it only to the operator account. Check
`docker version` and `docker compose version`.

## 4. DNS and configuration

Choose a development hostname under a domain you control, for example
`copilot-dev.example.com`, and point its **A record** to the server IPv4. Start
with DNS-only mode if your DNS provider has an HTTP proxy option. Add an AAAA
record only when the corresponding IPv6 address and routing have been checked.

Confirm it resolves to the server, then from the repository directory:

```bash
python3 deploy/development/configure.py copilot-dev.example.com
bash deploy/development/deploy.sh
```

The configure command prompts for a tester password (16+ characters, up to 72
UTF-8 bytes) without putting it in command history. The gate username is `tester`.
It creates `.env.development` with a random, URL-safe database password and
`deploy/development/secrets/users.caddy` containing a password hash. Both are
ignored by Git and Docker build contexts; keep them on the server. The script
refuses to overwrite existing settings. Do not regenerate the database password
for an existing PostgreSQL volume; changing it needs an explicit database change.

The deployment builds the frontend and API, validates Caddy configuration, starts
the database/inbox, creates a database dump, pauses the app for migrations, and
starts the new app. There is a short maintenance window during updates. Caddy
obtains and renews HTTPS certificates; first issuance requires correct DNS and
reachable ports 80/443. Wait for certificate issuance in the web logs if needed:

```bash
bash deploy/development/compose.sh ps
bash deploy/development/compose.sh logs --tail=100 web api
```

Open the HTTPS hostname, enter the tester gate credentials, then use the app's
normal signup/login. The gate is separate from an application account. The built
frontend is served by Caddy; no Vite development server is exposed. Secure cookies
and the exact HTTPS Origin are configured automatically.

## 5. Mailpit and acceptance test

Open an SSH tunnel from Windows PowerShell and leave it running:

```powershell
ssh -i "$env:USERPROFILE\.ssh\sdc-development" -N -L 18025:127.0.0.1:8025 deploy@SERVER_IP
```

View the inbox at **http://127.0.0.1:18025**. This local port avoids a conflict with
any native Mailpit running on your PC. All development mail is captured on this
server, including registration, verification, recovery and email-change links.
No email is delivered to external mailboxes and no SMTP provider is needed.
Only SSH-authorized operators can reach the inbox; testers do not receive server
access merely because they have the site's tester password.

Test with an example.com address: signup → open Mailpit → confirm email → login →
update profile → logout → reset password → login again. Restart the API and verify
account persistence. Optionally run the scripted check on the server:

```bash
python3 deploy/development/smoke.py https://copilot-dev.example.com
```

This prompts for the gate password, verifies the real TLS certificate, exercises
CSRF protection, creates an example.com test account, reads its email from local
Mailpit, and checks Secure cookies and logout. It leaves that test account in the
development database. CI performs the same check using Caddy's localhost CA.

To grant the first app administrator after verifying that account:

```bash
bash deploy/development/compose.sh exec api python -m app.accounts.cli promote YOUR_ACCOUNT_EMAIL
```

## 6. Updates, recovery and operational boundaries

Deploy reviewed commits from `main` manually for this first environment:

```bash
git pull --ff-only
bash deploy/development/deploy.sh
```

Do not reuse the local `docker compose up` command here: the wrapper selects the
standalone server configuration. Updates do not delete persistent volumes. A
reboot restarts the long-running services via Docker's restart policy. Database
migrations run explicitly during deployment, not on every process restart.

Each deployment saves a pre-migration custom-format PostgreSQL dump in
`backups/development/`. Keep a copy off-server if test data becomes valuable and
prune old local dumps deliberately as disk usage grows. Authentication record
cleanup can be run with:

```bash
bash deploy/development/compose.sh exec api python -m app.accounts.cli cleanup
```

If build/validation fails, the current app keeps running. If migration/startup
fails, the deployment stops with an error; inspect logs before restarting. It
does not blindly downgrade the database or automatically delete/restore volumes.
Rollback requires choosing compatible application code or restoring the matching
database dump during maintenance. Do not run `down -v` unless intentionally
resetting this disposable development environment.

The proxy's private address is `172.30.88.10`; the API trusts forwarded client IPs
only from that address. Caddy discards untrusted client-supplied forwarding headers.
Adjust both the subnet and trusted address together if an existing server network
conflicts. The database/mail network is internal. Mailpit also has a separate
bridge for publishing its inbox on host loopback; SMTP has no host port and no
outbound relay is configured. Messages expire after seven days or when the
200-message limit is reached. Container logs are bounded.

This provides development deployment, not the commercial launch gate. Production
requires its own host/data/secrets, real SMTP, off-server backup/restore acceptance,
monitoring and the remaining product/billing/privacy milestones. Automated GitHub
release deployment can follow once this first server deployment is accepted.

Sources: [Hetzner server creation](https://docs.hetzner.com/cloud/servers/getting-started/creating-a-server/),
[Hetzner firewall](https://docs.hetzner.com/cloud/firewalls/getting-started/creating-a-firewall/),
[Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/),
[Caddy basic authentication](https://caddyserver.com/docs/caddyfile/directives/basic_auth),
[Caddy proxy headers](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#headers).
