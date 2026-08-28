"""JWT 认证（§16/§27）：HS256 签名、过期、issuer 校验。

MVP 自签 JWT（OIDC/JWKS 外部验证后置）。claims：
    sub=user_id, tenant_id, roles[], iss, iat, exp
"""

import datetime

import jwt

from app.settings import Settings


def create_access_token(
    settings: Settings,
    *,
    tenant_id: str,
    user_id: str,
    roles: list[str] | None = None,
    expires_s: int | None = None,
) -> str:
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "roles": roles or [],
        "iss": settings.auth_jwt_issuer,
        "iat": now,
        "exp": now + datetime.timedelta(seconds=expires_s or settings.auth_jwt_expires_s),
    }
    return jwt.encode(payload, settings.auth_jwt_secret, algorithm=settings.auth_jwt_algorithm)


def decode_access_token(settings: Settings, token: str) -> dict:
    """校验签名/过期/issuer/必要 claims。失败抛 jwt 异常。"""
    return jwt.decode(
        token,
        settings.auth_jwt_secret,
        algorithms=[settings.auth_jwt_algorithm],
        issuer=settings.auth_jwt_issuer,
        options={"require": ["exp", "iat", "sub", "tenant_id"]},
    )
