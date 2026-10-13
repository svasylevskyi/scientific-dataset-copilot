from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Password = Annotated[str, StringConstraints(min_length=12, max_length=128)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmailInput(Input):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class RegisterInput(EmailInput):
    name: Name
    password: Password


class LoginInput(EmailInput):
    password: str = Field(min_length=1, max_length=128)


class TokenInput(Input):
    token: str = Field(min_length=20, max_length=200)


class ResetInput(TokenInput):
    password: Password


class ProfileInput(Input):
    name: Name


class PasswordInput(Input):
    current_password: str = Field(min_length=1, max_length=128)
    password: Password


class EmailChangeInput(EmailInput):
    current_password: str = Field(min_length=1, max_length=128)


class Message(BaseModel):
    message: str


class WorkspaceView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    created_at: datetime


class AccountView(BaseModel):
    id: UUID
    email: str
    name: str
    role: Literal["user", "admin"]
    verified: bool
    workspace: WorkspaceView


class SessionView(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    current: bool


class AdminSummary(BaseModel):
    users: int
    verified_users: int
    workspaces: int
