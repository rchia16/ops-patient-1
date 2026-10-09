"""Auth0 JWT verification for the MCP resource server."""
import time

import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier


class Auth0TokenVerifier(TokenVerifier):
    def __init__(self, issuer, audience, required_scope, jwks_url=None):
        self.issuer = issuer
        self.audience = audience
        self.required_scope = required_scope
        self.jwks = jwt.PyJWKClient(jwks_url or f"{issuer}.well-known/jwks.json")

    async def verify_token(self, token):
        try:
            key = self.jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError:
            return None

        scopes = set(str(claims.get("scope", "")).split())
        permissions = claims.get("permissions", [])
        if isinstance(permissions, list):
            scopes.update(str(item) for item in permissions)
        if self.required_scope not in scopes:
            return None
        expires_at = int(claims["exp"])
        if expires_at <= int(time.time()) or not str(claims.get("sub", "")).strip():
            return None
        return AccessToken(
            token=token,
            client_id=str(claims.get("azp") or claims.get("client_id") or "unknown"),
            scopes=sorted(scopes),
            expires_at=expires_at,
            resource=self.audience,
            subject=str(claims["sub"]),
            claims=claims,
        )
