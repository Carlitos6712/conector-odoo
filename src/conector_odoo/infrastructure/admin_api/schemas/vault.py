from typing import Literal

from pydantic import BaseModel


class VaultStatusOut(BaseModel):
    """Whether the credential vault has a key, and where it comes from. Never the key itself."""

    configured: bool
    source: Literal["env", "file"] | None
