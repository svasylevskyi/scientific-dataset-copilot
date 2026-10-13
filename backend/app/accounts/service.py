import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.accounts import mail
from app.accounts.models import AuthSession, EmailToken, User, Workspace
from app.accounts.schemas import AccountView, WorkspaceView
from app.accounts.security import digest, now, secret
from app.config import settings

COOKIE = "sdc_session"
COOKIE_PATH = "/api/v1"


@dataclass
class Identity:
    user: User
    session: AuthSession


def set_cookie(response: Response, session: AuthSession, raw: str) -> None:
    response.set_cookie(
        COOKIE,
        raw,
        max_age=max(0, int((session.expires_at - now()).total_seconds())),
        httponly=True,
        secure=settings().secure_cookies,
        samesite="lax",
        path=COOKIE_PATH,
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(
        COOKIE,
        path=COOKIE_PATH,
        httponly=True,
        secure=settings().secure_cookies,
        samesite="lax",
    )


def start_session(db: Session, user: User, response: Response) -> None:
    moment = now()
    session = AuthSession(
        user_id=user.id,
        token_hash="",
        created_at=moment,
        expires_at=moment + timedelta(days=7),
        absolute_expires_at=moment + timedelta(days=30),
    )
    db.add(session)
    db.flush()
    raw = f"{session.id}.{secret()}"
    session.token_hash = digest(raw)
    set_cookie(response, session, raw)


def identity(request: Request, db: Session, *, allow_previous: bool = False) -> Identity:
    raw = request.cookies.get(COOKIE, "")
    try:
        if len(raw) > 200:
            raise ValueError
        session_id = UUID(raw.split(".", 1)[0])
    except ValueError as exc:
        raise HTTPException(401, "Please sign in to continue.") from exc
    session = db.get(AuthSession, session_id)
    if not session:
        raise HTTPException(401, "Please sign in to continue.")
    # Always lock user before session/token. This serializes credential changes,
    # token consumption and login so a concurrent request cannot resurrect access.
    user = db.scalar(select(User).where(User.id == session.user_id).with_for_update())
    session = db.scalar(
        select(AuthSession)
        .where(AuthSession.id == session_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    moment = now()
    if (
        not user
        or not user.active
        or not user.verified_at
        or not session
        or session.revoked_at
        or session.expires_at <= moment
        or session.absolute_expires_at <= moment
    ):
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    token_hash = digest(raw)
    if not secrets.compare_digest(session.token_hash, token_hash):
        if session.previous_token_hash and secrets.compare_digest(
            session.previous_token_hash, token_hash
        ):
            if session.rotated_at and moment < session.rotated_at + timedelta(seconds=30):
                if allow_previous:
                    return Identity(user, session)
                # A concurrent refresh must never clear the winning response's cookie.
                raise HTTPException(409, "Session renewed in another tab. Please retry.")
            session.revoked_at = moment
            db.commit()  # Replay revocation must survive the error response.
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    return Identity(user, session)


def account_view(db: Session, user: User) -> AccountView:
    workspace = db.scalar(select(Workspace).where(Workspace.owner_id == user.id))
    return AccountView(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        verified=user.verified_at is not None,
        workspace=WorkspaceView.model_validate(workspace),
    )


def revoke_sessions(db: Session, user: User) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now())
    )


def invalidate_tokens(db: Session, user: User, purpose: str | None = None) -> None:
    statement = update(EmailToken).where(
        EmailToken.user_id == user.id, EmailToken.used_at.is_(None)
    )
    if purpose:
        statement = statement.where(EmailToken.purpose == purpose)
    db.execute(statement.values(used_at=now()))


def issue_email(db: Session, user: User, purpose: str, target: str | None = None) -> None:
    invalidate_tokens(db, user, purpose)
    raw = secret()
    recipient = target or user.email
    db.add(
        EmailToken(
            user_id=user.id,
            token_hash=digest(raw),
            purpose=purpose,
            target_email=recipient,
            expires_at=now()
            + (timedelta(hours=24) if purpose == "verify" else timedelta(minutes=30)),
        )
    )
    db.flush()
    # On delivery failure the whole account transaction rolls back; retry is safe.
    mail.send_link(recipient, purpose, raw)


def consume_token(db: Session, raw: str, purpose: str) -> tuple[User, EmailToken]:
    token = db.scalar(select(EmailToken).where(EmailToken.token_hash == digest(raw)))
    if not token:
        raise HTTPException(400, "This link is invalid or expired. Request a new one.")
    user = db.scalar(select(User).where(User.id == token.user_id).with_for_update())
    token = db.scalar(
        select(EmailToken)
        .where(EmailToken.id == token.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if (
        not user
        or not user.active
        or not token
        or token.purpose != purpose
        or token.used_at
        or token.expires_at <= now()
        or (purpose != "email" and token.target_email != user.email)
    ):
        raise HTTPException(400, "This link is invalid or expired. Request a new one.")
    token.used_at = now()
    return user, token
