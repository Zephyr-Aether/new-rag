"""Alembic env：async 引擎 + 项目元数据（替换 create_all 的生产路径）。

用法：
    make migrate-gen    # 生成新迁移（改动模型后）
    make migrate        # 升级到最新（生产：upgrade head；开发：SQLite 亦可）
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.settings import get_settings
from app.storage.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 用环境变量/应用设置覆盖 alembic.ini 中的 sqlalchemy.url
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # §57.4 SQLite 支持 alter_column（Expand/Migrate/Contract 的 Contract 步骤）
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
