# Logic for assign JWT and decoding

from datetime import datetime, timedelta, timezone

import jwt  # pyright: ignore[reportMissingImports]
from fastapi import HTTPException, status  # pyright: ignore[reportMissingImports]

from app.core.config import get_settings



settings = get_settings()


def create_access_token(user_id: int) -> str:
    """Create a signed JWT for the authenticated user.

    Args:
        user_id: Local user id stored in the ``sub`` claim.

    Returns:
        The encoded JWT string.
    """
    expire_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )

    payload = {
        "sub": str(user_id),
        "exp": expire_at,
    }

    return jwt.encode(
        payload, 
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT.

    Args:
        token: Encoded access token from the cookie or Authorization header.

    Returns:
        The JWT payload.

    Raises:
        HTTPException: 401 when the token is invalid or expired.
    """
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, or expired token",
        ) from exc