from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, EmailStr, SecretStr, field_validator

from app.models.enums import UserRole


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    email: str
    name: str
    role: UserRole
    created_at: datetime


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: SecretStr = Field(min_length=1, max_length=1024, repr=False)
    new_password: SecretStr = Field(min_length=12, max_length=128, repr=False)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value):
        return validate_password(value)


def validate_password(value: SecretStr) -> SecretStr:
    password = value.get_secret_value()
    if password.isspace() or "\x00" in password:
        raise ValueError("Password must not be blank or contain NUL")
    try:
        password.encode("utf-8")
    except UnicodeError:
        raise ValueError("Password must be valid UTF-8") from None
    return value


class NameChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("이름을 확인해 주세요.")
        value.encode("utf-8")
        return value


class AccountDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=1, max_length=1024, repr=False)


class SignupRequest(NameChangeRequest):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(max_length=320)
    password: SecretStr = Field(min_length=12, max_length=128, repr=False)
    organization_name: str = Field(min_length=1, max_length=255)
    role: UserRole = UserRole.ANALYST

    @field_validator("organization_name")
    @classmethod
    def validate_organization(cls, value):
        value = value.strip()
        if not value or "\x00" in value:
            raise ValueError("Organization name must not be blank or contain NUL")
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("Organization name must be valid UTF-8") from None
        return value

    @field_validator("password")
    @classmethod
    def validate_signup_password(cls, value):
        return validate_password(value)


class SignupResponse(UserResponse):
    organization_name: str
