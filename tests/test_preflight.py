"""生产启动预检（Phase 0）：fail-fast，缺失项清单明确。"""

import pytest

from app.common.preflight import preflight_or_raise, run_preflight
from app.settings import Settings


def _settings(**overrides) -> Settings:
    base = {
        "environment": "prod",
        "auth_require_jwt": True,
        "auth_jwt_secret": "a-strong-random-secret-for-prod-123456",
        "llm_provider": "mock",
        "database_url": "sqlite+aiosqlite:///:memory:",
    }
    base.update(overrides)
    return Settings(**base)


async def test_prod_rechecks_default_secret_defense_in_depth():
    # 构造时用强密钥通过 model_validator，再改回默认值 → preflight 应重新兜底报出
    s = _settings(auth_jwt_secret="a-strong-random-secret-for-prod-123456")
    s.auth_jwt_secret = "dev-secret-change-me"
    problems = await run_preflight(s)
    assert any("APP_AUTH_JWT_SECRET" in p for p in problems)


async def test_prod_blocks_llm_without_credentials():
    s = _settings(llm_provider="openai", llm_base_url="", llm_api_key="")
    problems = await run_preflight(s)
    joined = "\n".join(problems)
    assert "APP_LLM_BASE_URL" in joined
    assert "APP_LLM_API_KEY" in joined


async def test_dev_skips_preflight():
    s = _settings(environment="dev")
    await preflight_or_raise(s)  # 不抛即为通过


async def test_prod_unreachable_db_reported():
    s = _settings(database_url="postgresql+asyncpg://nobody:nobody@127.0.0.1:1/nope")
    problems = await run_preflight(s)
    assert any("数据库不可达" in p for p in problems)


def test_prod_preflight_raises_with_details():
    import asyncio

    # 用不可达 DB（构造可通过 model_validator）触发 RuntimeError，且异常信息带具体缺失项
    s = _settings(database_url="postgresql+asyncpg://nobody:nobody@127.0.0.1:1/nope")
    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(preflight_or_raise(s))
    assert "生产启动预检未通过" in str(excinfo.value)
    assert "数据库不可达" in str(excinfo.value)
