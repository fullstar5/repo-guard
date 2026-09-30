from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status  # pyright: ignore[reportMissingImports]
from fastapi.security import OAuth2PasswordBearer  # pyright: ignore[reportMissingImports]
from sqlalchemy import select  # pyright: ignore[reportMissingImports]
from sqlalchemy.ext.asyncio import AsyncSession  # pyright: ignore[reportMissingImports]

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.security import decode_access_token
from app.models.user import User

settings = get_settings()

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/github/callback",
    auto_error=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield one async database session for the current request.

    Returns:
        An open ``AsyncSession`` that is closed when the request ends.
    """
    async with AsyncSessionLocal() as session:
        yield session


def _extract_access_token(
    request: Request,
    bearer_token: str | None,
) -> str:
    """Read the access token from the Authorization header or the session cookie.

    Args:
        request: Incoming request, used to read the httpOnly cookie.
        bearer_token: Token parsed by the OAuth2 scheme, if the header is present.

    Returns:
        The raw JWT string.

    Raises:
        HTTPException: 401 when neither source has a token.
    """
    if bearer_token:
        return bearer_token

    cookie_token = request.cookies.get(settings.access_token_cookie_name)
    if cookie_token:
        return cookie_token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )


async def get_current_user(
    request: Request,
    bearer_token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the current user from a Bearer token or the httpOnly cookie.

    Args:
        request: Incoming request.
        bearer_token: Optional Authorization header token.
        db: Request-scoped async session.

    Returns:
        The ``User`` row named by the token ``sub`` claim.

    Raises:
        HTTPException: 401 when the token or user is missing or invalid.
    """
    token = _extract_access_token(request, bearer_token)
    payload = decode_access_token(token)
    user_id = payload.get("sub")

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user