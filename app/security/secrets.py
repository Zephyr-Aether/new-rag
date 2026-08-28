"""Secret Manager（§6.5 / §15.3 Secret Reference）加密持久化。

- 值 Fernet 加密落库（主密钥来自 `secret_encryption_key`，未设则从 `auth_jwt_secret` 派生）；
- `get()` 同步读缓存（工具执行期注入，无 IO）；`set/delete/list/load_all` 异步持久化；
- LLM/日志只出现 `credential_ref=xxx`，真实凭据由 Tool Runtime 执行阶段注入。
"""

import base64
import contextvars
import hashlib

from cryptography.fernet import Fernet
from sqlalchemy import delete, select

from app.common.errors import AgentError
from app.storage.models import SecretRow

_INJECTED_SECRET: contextvars.ContextVar[str | None] = contextvars.ContextVar("injected_secret", default=None)


class SecretNotFoundError(AgentError):
    code = "SECRET_NOT_FOUND"


def derive_key(source: str) -> bytes:
    """从任意字符串派生 Fernet 密钥（32 字节 urlsafe base64）。"""
    return base64.urlsafe_b64encode(hashlib.sha256(source.encode()).digest())


class SecretManager:
    def __init__(self, sessions=None, key_source: str | None = None):
        self._store: dict[str, str] = {}
        self._sessions = sessions
        self._fernet = Fernet(derive_key(key_source)) if key_source else None

    # ---- 同步读（工具执行期注入，无 IO）----
    def get(self, ref: str) -> str:
        value = self._store.get(ref)
        if value is None:
            raise SecretNotFoundError(f"secret not found: {ref}")
        return value

    def has(self, ref: str) -> bool:
        return ref in self._store

    def __len__(self) -> int:
        return len(self._store)

    # ---- 异步持久化（加密落库）----
    def _encrypt(self, value: str) -> str:
        if self._fernet is None:
            return value
        return self._fernet.encrypt(value.encode()).decode()

    def _decrypt(self, blob: str) -> str:
        if self._fernet is None:
            return blob
        return self._fernet.decrypt(blob.encode()).decode()

    async def load_all(self) -> None:
        """启动时从库加载全部密钥到缓存（解密）。"""
        if self._sessions is None:
            return
        async with self._sessions() as s:
            rows = (await s.scalars(select(SecretRow))).all()
        self._store = {r.ref: self._decrypt(r.value_encrypted) for r in rows}

    async def set(self, ref: str, value: str) -> None:
        self._store[ref] = value
        if self._sessions is not None:
            async with self._sessions() as s:
                row = await s.get(SecretRow, ref)
                encrypted = self._encrypt(value)
                if row is None:
                    s.add(SecretRow(ref=ref, value_encrypted=encrypted))
                else:
                    row.value_encrypted = encrypted
                await s.commit()

    async def delete(self, ref: str) -> None:
        self._store.pop(ref, None)
        if self._sessions is not None:
            async with self._sessions() as s:
                await s.execute(delete(SecretRow).where(SecretRow.ref == ref))
                await s.commit()

    async def list(self) -> list[str]:
        return sorted(self._store.keys())


def inject_secret(value: str):
    """§6.5 工具执行期间注入真实凭据（contextvar，执行后自动恢复）。"""
    token = _INJECTED_SECRET.set(value)

    def _reset() -> None:
        _INJECTED_SECRET.reset(token)

    return _reset


def get_injected_secret() -> str | None:
    """工具 fn 内读取注入的凭据。"""
    return _INJECTED_SECRET.get()
