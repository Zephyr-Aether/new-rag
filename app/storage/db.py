"""异步数据库访问：engine/session 工厂。

- 测试与开发默认 SQLite（aiosqlite），免外部服务；
- 生产配 postgresql+asyncpg（docker-compose 提供）。
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from app.storage.models import Base


def create_engine_and_sessions(database_url: str):
    """返回 (engine, sessionmaker)。SQLite 用 StaticPool 支持内存库。"""
    kwargs: dict = {}
    if database_url.startswith("sqlite"):
        # 内存库必须共享单连接；文件库用 NullPool，避免跨请求复用同一连接导致读到旧事务快照
        kwargs["poolclass"] = StaticPool if database_url in ("sqlite+aiosqlite://", "sqlite://") else NullPool
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_async_engine(database_url, **kwargs)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    return engine, sessions


async def create_all(engine) -> None:
    """建表（MVP 用 create_all；生产切换 Alembic 迁移，§57.4 Expand-Migrate-Contract）。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session(sessions) -> AsyncIterator[AsyncSession]:
    async with sessions() as session:
        yield session
