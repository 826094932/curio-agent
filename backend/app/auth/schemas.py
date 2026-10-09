from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class RegisterInput(LoginInput):
    nickname: str = Field(min_length=1, max_length=64)
