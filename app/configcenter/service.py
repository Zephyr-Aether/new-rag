"""ConfigService / FlagService（§30）：版本化配置与 Feature Flag。

配置只增不改：set 产生新版本行；回滚 = 读取指定版本。
Feature Flag 按 percentage / tenants / users 放量；规则版本化。
"""

import hashlib
import json
import uuid

from sqlalchemy import select

from app.storage.models import ConfigurationRow, FeatureFlagRow


class ConfigService:
    def __init__(self, sessions):
        self.sessions = sessions

    async def set(self, *, tenant_id: str, scope: str, scope_id: str, key: str, value) -> dict:
        """写配置（新版本）。"""
        async with self.sessions() as s:
            latest = await s.scalar(
                select(ConfigurationRow)
                .where(
                    ConfigurationRow.tenant_id == tenant_id,
                    ConfigurationRow.scope == scope,
                    ConfigurationRow.scope_id == scope_id,
                    ConfigurationRow.key == key,
                )
                .order_by(ConfigurationRow.version.desc())
            )
            version = (latest.version if latest else 0) + 1
            s.add(
                ConfigurationRow(
                    id=uuid.uuid4().hex,
                    tenant_id=tenant_id,
                    scope=scope,
                    scope_id=scope_id,
                    key=key,
                    value_json=json.dumps(value, ensure_ascii=False),
                    version=version,
                )
            )
            await s.commit()
        return {"key": key, "version": version}

    async def get(self, *, tenant_id: str, scope: str, scope_id: str, key: str) -> dict | None:
        """读最新配置。"""
        async with self.sessions() as s:
            row = await s.scalar(
                select(ConfigurationRow)
                .where(
                    ConfigurationRow.tenant_id == tenant_id,
                    ConfigurationRow.scope == scope,
                    ConfigurationRow.scope_id == scope_id,
                    ConfigurationRow.key == key,
                )
                .order_by(ConfigurationRow.version.desc())
            )
        if row is None:
            return None
        return {"key": row.key, "value": json.loads(row.value_json), "version": row.version}

    async def get_version(
        self, *, tenant_id: str, scope: str, scope_id: str, key: str, version: int
    ) -> dict | None:
        """§21 回滚 = 读取指定版本。"""
        async with self.sessions() as s:
            row = await s.scalar(
                select(ConfigurationRow).where(
                    ConfigurationRow.tenant_id == tenant_id,
                    ConfigurationRow.scope == scope,
                    ConfigurationRow.scope_id == scope_id,
                    ConfigurationRow.key == key,
                    ConfigurationRow.version == version,
                )
            )
        if row is None:
            return None
        return {"key": row.key, "value": json.loads(row.value_json), "version": row.version}


class FlagService:
    def __init__(self, sessions):
        self.sessions = sessions

    @staticmethod
    def _bucket(user_id: str) -> int:
        return int(hashlib.md5(user_id.encode()).hexdigest(), 16) % 100

    async def set_flag(self, *, tenant_id: str, key: str, rules: dict, enabled: bool = True) -> dict:
        async with self.sessions() as s:
            row = await s.scalar(
                select(FeatureFlagRow).where(FeatureFlagRow.tenant_id == tenant_id, FeatureFlagRow.key == key)
            )
            if row is None:
                s.add(
                    FeatureFlagRow(
                        id=uuid.uuid4().hex,
                        tenant_id=tenant_id,
                        key=key,
                        rules_json=json.dumps(rules, ensure_ascii=False),
                        enabled=enabled,
                    )
                )
            else:
                row.rules_json = json.dumps(rules, ensure_ascii=False)
                row.enabled = enabled
                row.version += 1
            await s.commit()
        return {"key": key, "enabled": enabled}

    async def is_enabled(self, *, tenant_id: str, key: str, user_id: str | None = None) -> bool:
        async with self.sessions() as s:
            row = await s.scalar(
                select(FeatureFlagRow).where(FeatureFlagRow.tenant_id == tenant_id, FeatureFlagRow.key == key)
            )
        if row is None or not row.enabled:
            return False
        rules = json.loads(row.rules_json or "{}")
        percentage = int(rules.get("percentage", 100))
        if user_id:
            if user_id in rules.get("users", []):
                return True
            if self._bucket(user_id) >= percentage:
                return False
        if rules.get("tenants") and tenant_id not in rules["tenants"]:
            return False
        return True
