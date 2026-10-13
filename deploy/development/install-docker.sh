#!/usr/bin/env bash
# Run as root on a fresh supported Ubuntu LTS server. Installs Engine and Compose.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then echo 'Run this installer with sudo.' >&2; exit 1; fi
. /etc/os-release
ubuntu_codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
case "$ID:$VERSION_ID:$ubuntu_codename" in
  ubuntu:24.04:noble|ubuntu:26.04:resolute) ;;
  *)
    echo 'This bootstrap script supports Ubuntu 24.04 (noble) and 26.04 (resolute).' >&2
    exit 1
    ;;
esac
apt-get update
apt-get install -y ca-certificates curl git python3
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $ubuntu_codename
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker version
docker compose version
