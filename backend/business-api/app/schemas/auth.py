from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictInt, model_validator

from app.models.enums import UserRole


class LoginRequest(BaseModel):
    # Preserve the existing case-sensitive email lookup policy; no implicit normalization.
    email: str = Field(min_length=1, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=1024, repr=False)


class TokenResponse(BaseModel):
    access_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class TokenPayload(BaseModel):
    sub: UUID
    organization_id: UUID
    role: UserRole
    exp: StrictInt
    iat: StrictInt

    @model_validator(mode="after")
    def valid_lifetime(self):
        if self.exp <= self.iat:
            raise ValueError("Invalid token lifetime")
        return self


class CurrentUser(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    organization_id: UUID
    email: str
    role: UserRole
