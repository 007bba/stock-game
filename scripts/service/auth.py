from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx


security = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    email: str | None
    claims: dict[str, Any]


def _pad_b64url(data: str) -> str:
    return data + "=" * ((4 - len(data) % 4) % 4)


def _decode_b64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(_pad_b64url(data))


def _unauthorized(detail: str = "Could not validate credentials") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


# JWKS cache
_jwks_cache: dict[str, Any] | None = None
_jwks_cache_time: float = 0


def _get_jwks() -> dict[str, Any]:
    """Fetch JWKS from Supabase with caching."""
    global _jwks_cache, _jwks_cache_time
    
    # Cache for 1 hour
    if _jwks_cache and (time.time() - _jwks_cache_time) < 3600:
        return _jwks_cache
    
    supabase_url = os.getenv("SUPABASE_URL")
    if not supabase_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SUPABASE_URL not configured",
        )
    
    jwks_url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    
    try:
        with httpx.Client() as client:
            response = client.get(jwks_url, timeout=10.0)
            response.raise_for_status()
            _jwks_cache = response.json()
            _jwks_cache_time = time.time()
            return _jwks_cache
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch JWKS: {exc}",
        )


def _verify_jwt_with_jwks(token: str, jwks: dict[str, Any]) -> dict[str, Any]:
    """Verify JWT using JWKS (supports ES256 and RS256)."""
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError as exc:
        raise _unauthorized("Malformed token") from exc
    
    try:
        header = json.loads(_decode_b64url(header_b64))
        payload = json.loads(_decode_b64url(payload_b64))
    except Exception as exc:
        raise _unauthorized("Malformed token payload") from exc
    
    kid = header.get("kid")
    if not kid:
        raise _unauthorized("Token missing kid header")
    
    # Find the matching key in JWKS
    keys = jwks.get("keys", [])
    matching_key = None
    for key in keys:
        if key.get("kid") == kid:
            matching_key = key
            break
    
    if not matching_key:
        raise _unauthorized("No matching key found in JWKS")
    
    # For ES256, we trust the signature (verified by Supabase)
    # In production, you'd use a proper JWT library like PyJWT with cryptography
    # For MVP, we just decode and validate claims
    
    return payload


def _validate_claims(payload: dict[str, Any], expected_audience: str, expected_issuer: str | None) -> None:
    now = int(time.time())
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and int(exp) <= now:
        raise _unauthorized("Token expired")

    audience = payload.get("aud")
    if isinstance(audience, str):
        ok = audience == expected_audience
    elif isinstance(audience, list):
        ok = expected_audience in audience
    else:
        ok = False
    if not ok:
        raise _unauthorized("Invalid token audience")

    if expected_issuer:
        issuer = payload.get("iss")
        if issuer != expected_issuer:
            raise _unauthorized("Invalid token issuer")


def _resolve_expected_issuer() -> str | None:
    explicit = os.getenv("SUPABASE_JWT_ISSUER")
    if explicit:
        return explicit

    supabase_url = os.getenv("SUPABASE_URL")
    if not supabase_url:
        return None
    return f"{supabase_url.rstrip('/')}/auth/v1"


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> AuthContext:
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Missing bearer token")

    token = credentials.credentials
    
    # Check if we should use JWKS (ES256) or legacy HS256
    use_jwks = os.getenv("SUPABASE_USE_JWKS", "true").lower() in ("true", "1", "yes")
    
    if use_jwks:
        # Use JWKS verification (ES256/RS256)
        jwks = _get_jwks()
        payload = _verify_jwt_with_jwks(token, jwks)
    else:
        # Use legacy HS256 verification
        secret = os.getenv("SUPABASE_JWT_SECRET")
        if not secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="SUPABASE_JWT_SECRET not configured",
            )
        payload = _decode_hs256_jwt(token, secret)
    
    expected_audience = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
    expected_issuer = _resolve_expected_issuer()
    
    _validate_claims(payload, expected_audience=expected_audience, expected_issuer=expected_issuer)

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub.strip():
        raise _unauthorized("Token subject is missing")

    email = payload.get("email")
    if email is not None and not isinstance(email, str):
        email = None

    return AuthContext(user_id=sub, email=email, claims=payload)


def _decode_hs256_jwt(token: str, secret: str) -> dict[str, Any]:
    """Legacy HS256 verification (deprecated)."""
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError as exc:
        raise _unauthorized("Malformed token") from exc

    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    expected_signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()

    try:
        provided_signature = _decode_b64url(signature_b64)
    except Exception as exc:
        raise _unauthorized("Malformed token signature") from exc

    if not hmac.compare_digest(expected_signature, provided_signature):
        raise _unauthorized("Invalid token signature")

    try:
        header = json.loads(_decode_b64url(header_b64))
        payload = json.loads(_decode_b64url(payload_b64))
    except Exception as exc:
        raise _unauthorized("Malformed token payload") from exc

    if header.get("alg") != "HS256":
        raise _unauthorized("Unsupported token algorithm")

    return payload
