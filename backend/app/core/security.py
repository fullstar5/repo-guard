# Logic for assign JWT and decoding

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, status

from app.core.config import get_settings



settings = get_settings()


def create_access_token(user_id: int) -> str:
    """Create a signed JWT for the authenticated user."""
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
    """Decode and verify JWT, raising 401 when invalid."""
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