"""Generate server-local settings once; passwords never appear in shell arguments."""

import argparse
import getpass
import os
import re
import secrets
import subprocess
from pathlib import Path

CADDY_IMAGE = "caddy:2.11.7-alpine"
ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("domain", help="DNS hostname, such as copilot-dev.example.com")
    args = parser.parse_args()
    domain = args.domain.lower()
    if domain != "localhost" and not re.fullmatch(
        r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
        r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?",
        domain,
    ):
        parser.error("Provide a DNS hostname without https://, a port, or a path")
    env_path = ROOT / ".env.development"
    users_path = ROOT / "deploy/development/secrets/users.caddy"
    if env_path.exists() or users_path.exists():
        parser.error(
            "Settings already exist. Keep the existing database password; edit deliberately."
        )
    password = getpass.getpass(
        "Choose the tester gate password (at least 16 characters): "
    )
    if (
        len(password) < 16
        or len(password.encode()) > 72
        or password != password.strip()
        or "\n" in password
        or "\r" in password
    ):
        parser.error(
            "Use 16+ characters, at most 72 UTF-8 bytes, without surrounding whitespace"
        )
    if password != getpass.getpass("Confirm tester gate password: "):
        parser.error("Passwords do not match")
    # Caddy reads stdin when --plaintext is omitted. No password in process listings/history.
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", CADDY_IMAGE, "caddy", "hash-password"],
        input=password + "\n",
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    )
    password_hash = result.stdout.strip()
    if not password_hash.startswith("$2"):
        raise RuntimeError("Caddy did not return a bcrypt hash")
    os.umask(0o077)
    users_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with users_path.open("x") as stream:
        stream.write(f"tester {password_hash}\n")
    with env_path.open("x") as stream:
        stream.write(f"SDC_DOMAIN={domain}\nSDC_DB_PASSWORD={secrets.token_hex(32)}\n")
    print("Created protected server-local configuration. Tester gate username: tester")
    print("Keep the password in your password manager; it is not stored in plaintext.")


if __name__ == "__main__":
    main()
