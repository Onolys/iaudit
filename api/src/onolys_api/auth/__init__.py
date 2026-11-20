"""Authentication (R1): Identity Platform ID tokens or `X-API-Key`, both resolving to a uid."""

from onolys_api.auth.deps import Authenticator, AuthUser, current_user, current_user_token_only

__all__ = ["AuthUser", "Authenticator", "current_user", "current_user_token_only"]
