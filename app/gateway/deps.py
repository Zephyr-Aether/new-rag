"""主体身份注入（§6.1 / §53.1）。

优先 Bearer JWT：
- alg=RS* 且配置了 OIDC => 走 JWKS 校验（外部 id_token）
- 否则走自签 HS256 校验
显式携带 token 但无效 => 一律 401；无 token 时回落 X-Tenant-Id/X-User-Id（dev）；
auth_require_jwt=True 时拒绝无有效 token 的请求。
"""

from typing import Annotated

import jwt
from fastapi import Depends, Header, Request

from app.common.contracts import Subject
from app.common.errors import AgentError
from app.gateway.auth import decode_access_token


def require_perm(action: str, resource: str = "*"):
    """权限 AOP（§6.2）：路由级权限校验依赖，跨端点复用。

    用法：`Depends(require_perm("model:configure", "*"))`。校验不通过抛 PERMISSION_DENIED。
    """

    async def _dep(request: Request, subject: Annotated[Subject, Depends(get_subject)]) -> Subject:
        state = request.app.state.agent
        decision = await state.policy.is_allowed(subject, action, resource)
        if not decision.allowed:
            raise AgentError(
                f"permission denied: {action}:{resource}",
                code="PERMISSION_DENIED",
                detail={"action": action, "resource": resource, "reason": decision.reason},
            )
        return subject

    return _dep


async def get_subject(
    request: Request,
    x_tenant_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> Subject:
    settings = request.app.state.agent.settings
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        try:
            header = jwt.get_unverified_header(token)
            oidc = getattr(request.app.state.agent, "oidc", None)
            if header.get("alg", "").startswith("RS") and oidc is not None:
                claims = await oidc.verify(token)
                mapper = getattr(request.app.state.agent, "oidc_tenant_mapper", None)
                tenant_id = mapper.map(claims) if mapper else None
                if not tenant_id:
                    raise AgentError("no tenant mapping for OIDC subject", code="AUTH_NO_TENANT")
                return Subject(tenant_id=tenant_id, user_id=claims["sub"])
            claims = decode_access_token(settings, token)
            return Subject(
                tenant_id=claims.get("tenant_id") or settings.seed_tenant,
                user_id=claims["sub"],
            )
        except AgentError:
            raise
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise AgentError("invalid or expired token", code="AUTH_INVALID_TOKEN") from exc
    if settings.auth_require_jwt:
        raise AgentError("authentication required", code="AUTH_REQUIRED")
    return Subject(
        tenant_id=x_tenant_id or settings.seed_tenant,
        user_id=x_user_id or settings.seed_user,
    )
