from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from conector_odoo.domain.auth import MAX_PASSWORD_LENGTH, MAX_USERNAME_LENGTH, AdminUser, Role
from conector_odoo.infrastructure.admin_api.schemas.common import StrictModel


class LoginIn(StrictModel):
    username: str = Field(min_length=1, max_length=MAX_USERNAME_LENGTH)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class UserOut(BaseModel):
    id: int
    username: str
    role: Role
    created_at: datetime

    @classmethod
    def of(cls, user: AdminUser) -> "UserOut":
        return cls(id=user.id, username=user.username, role=user.role, created_at=user.created_at)


class SessionOut(BaseModel):
    user: UserOut
    csrf_token: str
    expires_at: datetime


class UserListOut(BaseModel):
    items: list[UserOut]


class UserCreateIn(StrictModel):
    username: str = Field(min_length=1, max_length=MAX_USERNAME_LENGTH)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)
    role: Role


class UserPatchIn(StrictModel):
    role: Role | None = None
    password: str | None = Field(default=None, min_length=1, max_length=MAX_PASSWORD_LENGTH)

    @model_validator(mode="after")
    def _something_to_change(self) -> "UserPatchIn":
        if self.role is None and self.password is None:
            raise ValueError("provide a role or a password")
        return self
