from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.contracts.models import Business, Contract, Version
from app.model_config.transport import validate_endpoint

STAGES = {
    "decompose": "text",
    "report": "text",
    "feedback": "text",
    "insight": "text",
    "topic": "text",
    "topic_score": "text",
    "evaluate": "text",
    "predict": "text",
    "extract": "text",
    "review": "text",
    "retrospect": "text",
    "visual": "vision",
    "image": "vision",
}


class SourceWrite(Contract):
    id: UUID | None = None
    expected_lock_version: Version | None = None
    name: str = Field(min_length=1, max_length=80)
    provider: Literal["deepseek", "openai", "other"]
    capability: Literal["text", "vision"]
    endpoint: str = Field(max_length=500)
    model: str = Field(min_length=1, max_length=120)
    secret_ref: Literal["DEEPSEEK_KEY", "OPENAI_API_KEY"]
    timeout: int = Field(default=45, ge=1, le=600, strict=True)
    retries: Literal[0] = 0
    max_tokens: int | None = Field(default=None, ge=1, le=131072, strict=True)
    enabled: bool = True

    @field_validator("endpoint")
    @classmethod
    def endpoint_safe(cls, v):
        return validate_endpoint(v)

    @field_validator("name", "model")
    @classmethod
    def nonblank(cls, v):
        if not v.strip():
            raise ValueError("Cannot be blank")
        return v.strip()


class SourceView(SourceWrite):
    id: UUID
    version: int
    lock_version: Version
    credential_ready: bool


class ConfigQuery(Contract):
    business_code: Business


class BindingsWrite(ConfigQuery):
    expected_lock_version: str = Field(pattern=r"^(0|[1-9][0-9]{0,18})$")
    bindings: dict[str, UUID]

    @field_validator("bindings")
    @classmethod
    def stages(cls, v):
        if set(v) - STAGES.keys():
            raise ValueError("Unknown stage")
        return v


class ConfigView(Contract):
    sources: list[SourceView]
    bindings: dict[str, UUID]
    lock_version: str
