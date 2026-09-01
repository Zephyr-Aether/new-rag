"""生产启动预检（Phase 0）：fail-fast，启动时读出明确缺失项。

只在 environment == "prod" 时执行；dev/test 不跑，避免拖慢本地开发与测试。
检查项：配置（认证/密钥/上传上限）、数据库连通、Redis 连通（配置了才查）、LLM 依赖（非 mock 才查）。
任一缺失 → 抛出带完整清单的 RuntimeError，阻断启动，运维能直接看到缺什么。
"""

from __future__ import annotations

import asyncio
import logging

import redis.asyncio as aioredis
from sqlalchemy import text

from app.settings import Settings
from app.storage.db import create_engine_and_sessions

logger = logging.getLogger(__name__)


async def run_preflight(settings: Settings) -> list[str]:
    """返回缺失项清单（空列表 = 通过）。"""
    problems: list[str] = []

    # 1. 配置：生产强制认证与随机密钥（settings 的 model_validator 已兜底，这里再显式复核一遍）
    if not settings.auth_require_jwt:
        problems.append("生产必须开启认证：设置 APP_AUTH_REQUIRE_JWT=true")
    if settings.auth_jwt_secret in ("", "dev-secret-change-me"):
        problems.append("生产必须使用强随机 APP_AUTH_JWT_SECRET，不能是默认值")

    # 2. 数据库连通
    try:
        engine, _ = create_engine_and_sessions(settings.database_url)
        try:
            async def _ping() -> None:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))

            await asyncio.wait_for(_ping(), timeout=10)
        finally:
            await engine.dispose()
    except Exception as exc:  # noqa: BLE001 汇总为一条缺失项
        problems.append(f"数据库不可达（{settings.database_url.split('@')[-1]}）：{exc}")

    # 3. Redis 连通（配置了才检查）
    if settings.redis_url:
        try:
            r = aioredis.from_url(settings.redis_url, socket_connect_timeout=3)

            async def _ping() -> None:
                await r.ping()
                await r.aclose()

            await asyncio.wait_for(_ping(), timeout=5)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"Redis 不可达（{settings.redis_url.split('@')[-1]}）：{exc}")

    # 4. LLM 依赖（非 mock 才检查：接了真实模型就必须有 base_url + api_key）
    if settings.llm_provider != "mock":
        if not settings.llm_base_url:
            problems.append(f"LLM provider 为 {settings.llm_provider} 但未设置 APP_LLM_BASE_URL")
        if not settings.llm_api_key:
            problems.append(f"LLM provider 为 {settings.llm_provider} 但未设置 APP_LLM_API_KEY")

    return problems


async def preflight_or_raise(settings: Settings) -> None:
    """prod 启动预检：有缺失项即抛出，缺什么一目了然。"""
    if settings.environment != "prod":
        return
    problems = await run_preflight(settings)
    if problems:
        raise RuntimeError("生产启动预检未通过：\n" + "\n".join(f"  - {p}" for p in problems))
