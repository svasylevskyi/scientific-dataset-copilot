"""Check the development HTTPS gateway and real account/email flow (standard library only)."""

import argparse
import base64
import getpass
import http.cookiejar
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "origin", help="HTTPS origin, e.g. https://copilot-dev.example.com"
    )
    parser.add_argument(
        "--ca-file", help="Explicit local CA for the CI localhost certificate"
    )
    args = parser.parse_args()
    origin = args.origin.rstrip("/")
    assert urllib.parse.urlsplit(origin).scheme == "https", "Use the HTTPS origin"
    password = getpass.getpass("Tester gate password: ")
    authorization = "Basic " + base64.b64encode(f"tester:{password}".encode()).decode()
    context = ssl.create_default_context(cafile=args.ca_file)
    cookies = http.cookiejar.CookieJar()
    browser = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        urllib.request.HTTPCookieProcessor(cookies),
    )

    def request(path, body=None, *, gate=True, csrf=True):
        headers = {"Authorization": authorization} if gate else {}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
            if csrf:
                headers.update({"Origin": origin, "X-SDC-Request": "1"})
        try:
            return browser.open(
                urllib.request.Request(origin + path, data=data, headers=headers),
                timeout=15,
            )
        except urllib.error.HTTPError as error:
            return error

    assert request("/", gate=False).status == 401, "App must require the tester gate"
    assert request("/api/v1/health", gate=False).status == 401, (
        "API must require the tester gate"
    )
    assert b'<div id="root">' in request("/").read(), "Compiled frontend is missing"
    assert json.load(request("/api/v1/ready"))["status"] == "ready"
    assert request("/api/v1/reference.csv").status == 200
    email = f"deployment-smoke-{time.time_ns()}@example.com"
    credentials = {"email": email, "password": "A unique deployment smoke passphrase!"}
    assert (
        request(
            "/api/v1/auth/register",
            {**credentials, "name": "Deployment check"},
            csrf=False,
        ).status
        == 403
    )
    assert (
        request(
            "/api/v1/auth/register", {**credentials, "name": "Deployment check"}
        ).status
        == 202
    )
    query = urllib.parse.urlencode({"query": f"to:{email}"})
    with urllib.request.urlopen(
        f"http://127.0.0.1:8025/api/v1/search?{query}", timeout=10
    ) as response:
        messages = json.load(response)["messages"]
    assert len(messages) == 1, "Verification email was not captured"
    with urllib.request.urlopen(
        f"http://127.0.0.1:8025/api/v1/message/{messages[0]['ID']}", timeout=10
    ) as response:
        message = json.load(response)
    token = re.search(
        re.escape(origin) + r"/#/verify\?token=([A-Za-z0-9_-]+)", message["Text"]
    )
    assert token, "Email link must use the configured HTTPS origin"
    assert request("/api/v1/auth/verify", {"token": token.group(1)}).status == 200
    login = request("/api/v1/auth/login", credentials)
    assert login.status == 200
    session_cookie = login.headers.get("Set-Cookie", "")
    assert "Secure" in session_cookie and "HttpOnly" in session_cookie
    account = json.load(login)
    assert request("/api/v1/workspaces/" + account["workspace"]["id"]).status == 200
    assert request("/api/v1/auth/me").status == 200
    assert request("/api/v1/auth/logout", {}).status == 200
    assert request("/api/v1/auth/me").status == 401
    # No database dump content is printed or modified by this check.
    assert any(Path("backups/development").glob("*.dump")), (
        "Pre-migration backup is missing"
    )
    print(
        "PASS: HTTPS, tester gate, compiled frontend, API, email links, Secure cookies and logout"
    )


if __name__ == "__main__":
    main()
