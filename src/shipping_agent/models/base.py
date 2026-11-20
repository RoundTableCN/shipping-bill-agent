"""Base model configuration."""

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Reject unknown fields. Extensions must go through a versioned schema."""

    model_config = ConfigDict(extra="forbid")
