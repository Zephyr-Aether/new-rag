"""OIDC/JWKS 外部身份校验（§16 升级）。

对外部签发的 RS256 id_token：按 kid 从 JWKS 取公钥 → 校验 签名/iss/aud/exp。
JWKS 缓存（默认 300s），kid 未命中时刷新一次。
"""

import json
import time

import httpx
import jwt

from app.settings import Settings


class OidcTenantMapper:
    """§16 OIDC claim→tenant：① claim 值 ② email 域名 ③ 默认。"""

    def __init__(self, settings: Settings):
        self.claim = settings.oidc_tenant_claim or "tenant_id"
        try:
            self.email_domains = json.loads(settings.oidc_tenant_email_domains or "{}")
        except json.JSONDecodeError:
            self.email_domains = {}
        self.default = settings.oidc_default_tenant

    def map(self, claims: dict) -> str | None:
        val = claims.get(self.claim)
        if isinstance(val, str) and val:
            return val
        email = claims.get("email", "")
        domain = email.rsplit("@", 1)[-1] if "@" in email else ""
        if domain in self.email_domains:
            return self.email_domains[domain]
        return self.default or None


class OidcVerifier:
    def __init__(self, settings: Settings, transport=None):
        self.jwks_url = settings.oidc_jwks_url
        self.issuer = settings.oidc_issuer
        self.audience = settings.oidc_audience
        self.transport = transport  # 测试注入 MockTransport
        self._keys: list[dict] = []
        self._fetched_at = 0.0

    async def _fetch_keys(self) -> None:
        async with httpx.AsyncClient(timeout=5.0, transport=self.transport) as c:
            r = await c.get(self.jwks_url)
            r.raise_for_status()
        self._keys = r.json().get("keys", [])
        self._fetched_at = time.time()

    def _get_key(self, kid: str) -> dict | None:
        return next((k for k in self._keys if k.get("kid") == kid), None)

    async def verify(self, token: str) -> dict:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        # 缓存冷/过期 => 拉取；kid 未命中 => 刷新一次（key rotation）
        if not self._keys or time.time() - self._fetched_at > 300:
            await self._fetch_keys()
        key = self._get_key(kid)
        if key is None:
            await self._fetch_keys()
            key = self._get_key(kid)
        if key is None:
            raise jwt.PyJWTError(f"kid {kid} not found in JWKS")
        alg = header.get("alg", "RS256")
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
        return jwt.decode(
            token,
            public_key,
            algorithms=[alg],
            issuer=self.issuer,
            audience=self.audience,
            options={"require": ["exp", "iss", "aud"]},
        )
