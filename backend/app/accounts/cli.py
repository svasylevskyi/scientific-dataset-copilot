"""Explicit local operator commands; no default administrator or shared password."""

import argparse
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.accounts.models import AuthSession, EmailToken, RateBucket, User
from app.accounts.security import now
from app.db import engine


def main():
    parser = argparse.ArgumentParser(description="Manage SDC accounts locally")
    commands = parser.add_subparsers(dest="command", required=True)
    for operation in ("promote", "demote"):
        command = commands.add_parser(operation)
        command.add_argument("email")
    commands.add_parser(
        "cleanup", help="Remove expired rate buckets and old authentication records"
    )
    args = parser.parse_args()
    with Session(engine()) as db, db.begin():
        if args.command == "cleanup":
            db.execute(delete(RateBucket).where(RateBucket.expires_at < now()))
            cutoff = now() - timedelta(days=7)
            db.execute(delete(EmailToken).where(EmailToken.expires_at < cutoff))
            db.execute(delete(AuthSession).where(AuthSession.expires_at < cutoff))
            print("Expired authentication records removed.")
            return
        user = db.scalar(
            select(User).where(User.email == args.email.strip().lower()).with_for_update()
        )
        if not user or not user.active or not user.verified_at:
            parser.error("An active, verified account is required")
        user.role = "admin" if args.command == "promote" else "user"
        print(f"Role set to {user.role}.")


if __name__ == "__main__":
    main()
