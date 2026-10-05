from pydantic import BaseModel, ConfigDict  # pyright: ignore[reportMissingImports]


class GitHubAccessTokenResponse(BaseModel):
    access_token: str
    token_type: str
    scope: str = ""
    expires_in: int | None = None
    refresh_token: str | None = None
    refresh_token_expires_in: int | None = None


class GitHubUserProfile(BaseModel):
    id: int
    login: str
    email: str | None = None


class GitHubEmail(BaseModel):
    email: str
    primary: bool
    verified: bool


class AuthUserRead(BaseModel):
    id: int
    github_id: int
    github_login: str
    email: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUserRead


class GitHubOAuthCallbackResponse(AuthTokenResponse):
    pass