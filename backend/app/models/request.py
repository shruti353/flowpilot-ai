"""Inbound request models for the agent API."""

from pydantic import BaseModel, Field, field_validator


class AgentPlanRequest(BaseModel):
    """A single natural-language request to turn into an execution plan."""

    text: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Natural-language description of what the user wants to do.",
    )

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be empty or blank")
        return value
