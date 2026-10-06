from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Request bodies reject unknown fields, so a typo never silently does nothing."""

    model_config = ConfigDict(extra="forbid")
