from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel

from conector_odoo.application.active_odoo import ActiveOdooStatus
from conector_odoo.infrastructure.admin_api.schemas.common import StrictModel


class ActivateOdooIn(StrictModel):
    profile_id: int


class ActiveOdooOut(BaseModel):
    """The live Odoo connection. Never carries a credential, only where it points."""

    source: Literal["profile", "env", "none"]
    profile_id: int | None
    profile_name: str | None
    base_url: str | None
    db: str | None
    login: str | None
    last_connected_at: datetime | None
    # ``active``; ``not_configured``; ``fallback`` (the stored active profile could not be
    # loaded at startup, see ``warning``).
    status: Literal["active", "not_configured", "fallback"]
    warning: str | None

    @classmethod
    def of(cls, status: ActiveOdooStatus) -> Self:
        return cls(
            source=status.source.value,
            profile_id=status.profile_id,
            profile_name=status.profile_name,
            base_url=status.base_url,
            db=status.db,
            login=status.login,
            last_connected_at=status.last_connected_at,
            status=status.status,
            warning=status.warning,
        )
