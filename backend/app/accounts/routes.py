from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts.models import AuthSession, User, Workspace
from app.accounts.rate_limit import limit_request
from app.accounts.schemas import (
    AccountView,
    AdminSummary,
    EmailChangeInput,
    EmailInput,
    LoginInput,
    Message,
    PasswordInput,
    ProfileInput,
    RegisterInput,
    ResetInput,
    SessionView,
    TokenInput,
    WorkspaceView,
)
from app.accounts.security import DUMMY_HASH, digest, now, password_hasher, password_matches, secret
from app.accounts.service import (
    account_view,
    clear_cookie,
    consume_token,
    identity,
    invalidate_tokens,
    issue_email,
    revoke_sessions,
    set_cookie,
    start_session,
)
from app.config import settings
from app.db import get_db
from app.plans.service import assign_default

Db = Annotated[Session, Depends(get_db, scope="function")]


def browser_write(request: Request) -> None:
    if request.method in {"POST", "PATCH", "DELETE"}:
        if (
            request.headers.get("origin") != settings().origin
            or request.headers.get("x-sdc-request") != "1"
            or request.headers.get("content-type", "").split(";")[0] != "application/json"
        ):
            raise HTTPException(403, "This request must come from the application.")


router = APIRouter(prefix="/api/v1", tags=["Accounts"], dependencies=[Depends(browser_write)])
GENERIC = Message(message="If this address is eligible, an email is on its way. Check your inbox.")


@router.post("/auth/register", response_model=Message, status_code=202)
def register(body: RegisterInput, request: Request, db: Db):
    limit_request(request, "register", body.email)
    user_id = db.scalar(
        insert(User)
        .values(
            id=uuid4(),
            email=body.email,
            name=body.name,
            password_hash=password_hasher.hash(body.password),
            role="user",
            active=True,
        )
        .on_conflict_do_nothing(index_elements=[User.email])
        .returning(User.id)
    )
    user = db.scalar(select(User).where(User.email == body.email).with_for_update())
    if user_id:
        workspace = Workspace(owner_id=user_id)
        db.add(workspace)
        assign_default(db, workspace)
    if user and user.active and not user.verified_at:
        issue_email(db, user, "verify")
    return GENERIC


@router.post("/auth/resend-verification", response_model=Message, status_code=202)
def resend(body: EmailInput, request: Request, db: Db):
    limit_request(request, "resend", body.email)
    user = db.scalar(select(User).where(User.email == body.email).with_for_update())
    if user and user.active and not user.verified_at:
        issue_email(db, user, "verify")
    return GENERIC


@router.post("/auth/verify", response_model=Message)
def verify(body: TokenInput, request: Request, db: Db):
    limit_request(request, "verify")
    user, _ = consume_token(db, body.token, "verify")
    user.verified_at = now()
    return Message(message="Email verified. You can now sign in.")


@router.post("/auth/login", response_model=AccountView)
def login(body: LoginInput, request: Request, response: Response, db: Db):
    limit_request(request, "login", body.email)
    user = db.scalar(select(User).where(User.email == body.email).with_for_update())
    valid = password_matches(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid or not user.active:
        raise HTTPException(401, "Email or password is incorrect.")
    if not user.verified_at:
        raise HTTPException(403, "Verify your email before signing in. You can request a new link.")
    if password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = password_hasher.hash(body.password)
    start_session(db, user, response)
    return account_view(db, user)


@router.get("/auth/me", response_model=AccountView)
def me(request: Request, db: Db):
    return account_view(db, identity(request, db).user)


@router.post("/auth/refresh", response_model=Message)
def refresh(request: Request, response: Response, db: Db):
    from datetime import timedelta

    account = identity(request, db)
    session = account.session
    raw = f"{session.id}.{secret()}"
    session.previous_token_hash = session.token_hash
    session.token_hash = digest(raw)
    session.rotated_at = now()
    session.expires_at = min(now() + timedelta(days=7), session.absolute_expires_at)
    set_cookie(response, session, raw)
    return Message(message="Session renewed.")


@router.post("/auth/logout", response_model=Message)
def logout(request: Request, response: Response, db: Db):
    try:
        identity(request, db, allow_previous=True).session.revoked_at = now()
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
    clear_cookie(response)
    return Message(message="Signed out.")


@router.post("/auth/forgot-password", response_model=Message, status_code=202)
def forgot(body: EmailInput, request: Request, db: Db):
    limit_request(request, "forgot", body.email)
    user = db.scalar(select(User).where(User.email == body.email).with_for_update())
    if user and user.active and user.verified_at:
        issue_email(db, user, "reset")
    return GENERIC


@router.post("/auth/reset-password", response_model=Message)
def reset(body: ResetInput, request: Request, response: Response, db: Db):
    limit_request(request, "reset")
    user, _ = consume_token(db, body.token, "reset")
    user.password_hash = password_hasher.hash(body.password)
    revoke_sessions(db, user)
    invalidate_tokens(db, user)
    clear_cookie(response)
    return Message(message="Password reset. Sign in with your new password.")


@router.patch("/account", response_model=AccountView)
def profile(body: ProfileInput, request: Request, db: Db):
    user = identity(request, db).user
    user.name = body.name
    return account_view(db, user)


@router.post("/account/password", response_model=Message)
def change_password(body: PasswordInput, request: Request, response: Response, db: Db):
    limit_request(request, "password")
    user = identity(request, db).user
    if not password_matches(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect.")
    user.password_hash = password_hasher.hash(body.password)
    revoke_sessions(db, user)
    invalidate_tokens(db, user)
    clear_cookie(response)
    return Message(message="Password changed. Sign in again on each device.")


@router.post("/account/email", response_model=Message, status_code=202)
def change_email(body: EmailChangeInput, request: Request, db: Db):
    limit_request(request, "email-change", body.email)
    user = identity(request, db).user
    if not password_matches(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect.")
    existing = db.scalar(select(User.id).where(User.email == body.email))
    if not existing:
        issue_email(db, user, "email", body.email)
    return GENERIC


@router.post("/auth/confirm-email", response_model=Message)
def confirm_email(body: TokenInput, request: Request, response: Response, db: Db):
    limit_request(request, "confirm-email")
    user, token = consume_token(db, body.token, "email")
    try:
        with db.begin_nested():
            user.email = token.target_email
            db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            400, "This email change cannot be completed. Request a new link."
        ) from exc
    revoke_sessions(db, user)
    invalidate_tokens(db, user)
    clear_cookie(response)
    return Message(message="Email changed. Sign in using your new email.")


@router.get("/account/sessions", response_model=list[SessionView])
def sessions(request: Request, db: Db):
    account = identity(request, db)
    rows = db.scalars(
        select(AuthSession)
        .where(
            AuthSession.user_id == account.user.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now(),
            AuthSession.absolute_expires_at > now(),
        )
        .order_by(AuthSession.created_at.desc())
    )
    return [
        SessionView(
            id=row.id,
            created_at=row.created_at,
            expires_at=row.expires_at,
            current=row.id == account.session.id,
        )
        for row in rows
    ]


@router.delete("/account/sessions/{session_id}", response_model=Message)
def revoke_session(session_id: UUID, request: Request, response: Response, db: Db):
    account = identity(request, db)
    session = db.scalar(
        select(AuthSession)
        .where(
            AuthSession.id == session_id,
            AuthSession.user_id == account.user.id,
        )
        .with_for_update()
    )
    if not session:
        raise HTTPException(404, "Session not found.")
    session.revoked_at = now()
    if session.id == account.session.id:
        clear_cookie(response)
    return Message(message="Session signed out.")


@router.post("/account/logout-all", response_model=Message)
def logout_all(request: Request, response: Response, db: Db):
    revoke_sessions(db, identity(request, db).user)
    clear_cookie(response)
    return Message(message="Signed out on all devices.")


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceView)
def workspace(workspace_id: UUID, request: Request, db: Db):
    user = identity(request, db).user
    workspace = db.scalar(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.owner_id == user.id,
        )
    )
    if not workspace:
        raise HTTPException(404, "Workspace not found.")
    return workspace


@router.get("/admin/summary", response_model=AdminSummary)
def admin_summary(request: Request, db: Db):
    if identity(request, db).user.role != "admin":
        raise HTTPException(403, "Administrator access is required.")
    return AdminSummary(
        users=db.scalar(select(func.count()).select_from(User)),
        verified_users=db.scalar(
            select(func.count()).select_from(User).where(User.verified_at.is_not(None))
        ),
        workspaces=db.scalar(select(func.count()).select_from(Workspace)),
    )
