import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.contracts.models import Contract, NonEmpty, Version

Role = Literal["administrator", "user"]
Password = Annotated[
    str, Field(min_length=8, max_length=1024, json_schema_extra={"writeOnly": True})
]


class AccessView(Contract):
    enabled: bool
    setup_required: bool
    org_id: UUID | None


class RegisterRequest(Contract):
    email: Annotated[str, Field(min_length=3, max_length=254)]
    password: Password
    display_name: Annotated[NonEmpty, Field(max_length=100)] | None = None

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        value = value.strip().lower()
        local, separator, domain = value.partition("@")
        if (
            not separator
            or len(local) > 64
            or not re.fullmatch(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]+", local)
            or local.startswith(".")
            or local.endswith(".")
            or ".." in local
            or len(domain) > 253
            or "." not in domain
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
                for part in domain.split(".")
            )
            or not re.fullmatch(r"[a-z]{2,63}", domain.rsplit(".", 1)[-1])
        ):
            raise ValueError("A valid email address is required")
        return value


class SetupRequest(Contract):
    login_name: Annotated[NonEmpty, Field(max_length=100)]
    display_name: Annotated[NonEmpty, Field(max_length=100)]
    password: Password


class UserCreate(SetupRequest):
    login_name: Annotated[NonEmpty, Field(max_length=254)]
    role: Role

    @field_validator("login_name")
    @classmethod
    def valid_login_email(cls, value):
        return RegisterRequest.valid_email(value)


class UserUpdate(Contract):
    expected_version: Version
    display_name: Annotated[NonEmpty, Field(max_length=100)] | None = None
    role: Role | None = None
    enabled: bool | None = None
    password: Password | None = None

    @model_validator(mode="after")
    def require_change(self):
        fields = self.model_fields_set - {"expected_version"}
        if not fields or any(getattr(self, key) is None for key in fields):
            raise ValueError("At least one non-null change is required")
        return self


class UserView(Contract):
    id: UUID
    login_name: str
    display_name: str
    role: Role
    enabled: bool
    lock_version: Version
    created_at: AwareDatetime


class UserList(Contract):
    items: list[UserView]
