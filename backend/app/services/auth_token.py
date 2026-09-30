from app.core.security import create_access_token
from app.models.user import User
from app.schemas.auth import AuthTokenResponse, AuthUserRead



def build_auth_response(user: User) -> AuthTokenResponse:
    """Build the login payload for a stored user.

    Args:
        user: User row that just signed in.

    Returns:
        An access token plus the public user fields.
    """
    access_token = create_access_token(user.id)

    return AuthTokenResponse(
        access_token=access_token,
        user=AuthUserRead.model_validate(user),
    )