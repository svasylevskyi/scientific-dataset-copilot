"""Shared fixed-window limits, committed independently of the account transaction."""

from datetime import UTC, datetime

from fastapi import HTTPException, Request
from sqlalchemy.dialects.postgresql import insert

from app.accounts.models import RateBucket
from app.accounts.security import digest, now
from app.db import engine


def consume(key: str, limit: int, seconds: int) -> None:
    timestamp = int(now().timestamp())
    window = timestamp // seconds
    expires = (window + 1) * seconds
    statement = insert(RateBucket).values(
        key=digest(f"{key}:{window}"), count=1, expires_at=datetime.fromtimestamp(expires, UTC)
    )
    statement = statement.on_conflict_do_update(
        index_elements=[RateBucket.key], set_={"count": RateBucket.count + 1}
    ).returning(RateBucket.count)
    with engine().begin() as connection:
        count = connection.execute(statement).scalar_one()
    if count > limit:
        raise HTTPException(
            429,
            "Too many attempts. Please wait before trying again.",
            headers={"Retry-After": str(expires - timestamp)},
        )


def limit_request(request: Request, action: str, email: str | None = None) -> None:
    # Trust only the server's client address, never an arbitrary forwarding header.
    address = request.client.host if request.client else "unknown"
    consume(f"ip:{address}", 60, 300)
    if email:
        if action in {"register", "resend", "forgot", "email-change"}:
            mail_action = "verify" if action in {"register", "resend"} else action
            consume(f"mail:{mail_action}:{email}", 1, 60)
        else:
            consume(f"{action}:{email}", 10, 900)
