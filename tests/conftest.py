"""测试公共夹具：独立 SQLite + mock provider 的依赖容器。

注意：环境变量必须先于 app 导入设置（get_settings 有 lru_cache）。
"""

import os
import tempfile
import uuid

_tmpdir = tempfile.mkdtemp(prefix="agent_platform_tests_")
# 测试不读开发者 .env：指向不存在的文件，用例结果与本机 .env 内容解耦
os.environ.setdefault("APP_ENV_FILE", "/nonexistent/agent-platform-test.env")
os.environ.setdefault("APP_DATABASE_URL", f"sqlite+aiosqlite:///{_tmpdir}/test.db")
os.environ.setdefault("APP_LLM_PROVIDER", "mock")
os.environ.setdefault("APP_REDIS_URL", "")
os.environ.setdefault("APP_ENVIRONMENT", "test")

import pytest_asyncio  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.agent.model.gateway import ModelGateway  # noqa: E402
from app.agent.runtime.cancel import CancelService  # noqa: E402
from app.agent.runtime.runtime import RuntimeDeps  # noqa: E402
from app.agent.runtime.store import RunStore  # noqa: E402
from app.graph.service import GraphService, register_graph_tool  # noqa: E402
from app.graph.store import GraphStore  # noqa: E402
from app.knowledge.embedding import HashEmbedding  # noqa: E402
from app.knowledge.retrieval import KnowledgeService, register_knowledge_tool  # noqa: E402
from app.knowledge.store import KnowledgeStore  # noqa: E402
from app.security.audit import AuditService  # noqa: E402
from app.security.policy import PolicyEngine  # noqa: E402
from app.settings import Settings  # noqa: E402
from app.storage.db import create_all, create_engine_and_sessions  # noqa: E402
from app.storage.lock import RunLockService  # noqa: E402
from app.storage.models import PolicyRow  # noqa: E402
from app.tool.limiter import RateLimiter  # noqa: E402
from app.tool.registry import default_registry  # noqa: E402
from app.tool.runtime import ToolRuntime  # noqa: E402

TEST_TENANT = "t"
TEST_USER = "u"
# 测试租户的最小 allow 策略（default-deny 生效的前提）
TEST_POLICIES = [
    ("tool:execute", "calc.add"),
    ("tool:execute", "echo"),
    ("tool:execute", "http.get"),
    ("tool:execute", "kb.search"),
    ("tool:execute", "graph.query"),
]


async def _seed_test_policies(sessions) -> None:
    async with sessions() as s:
        existing = await s.scalar(select(PolicyRow.id).where(PolicyRow.tenant_id == TEST_TENANT).limit(1))
        if existing:
            return
        for action, resource in TEST_POLICIES:
            s.add(
                PolicyRow(
                    id=f"pol-{uuid.uuid4().hex[:8]}",
                    tenant_id=TEST_TENANT,
                    name="test-allow",
                    effect="ALLOW",
                    action=action,
                    resource=resource,
                )
            )
        await s.commit()


@pytest_asyncio.fixture
async def sessions(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/runtime.db"
    engine, sessions = create_engine_and_sessions(url)
    await create_all(engine)
    await _seed_test_policies(sessions)
    yield sessions
    await engine.dispose()


@pytest_asyncio.fixture
def store(sessions):
    return RunStore(sessions)


@pytest_asyncio.fixture
def registry():
    return default_registry()


@pytest_asyncio.fixture
def gateway():
    return ModelGateway(Settings(database_url="sqlite+aiosqlite://", llm_provider="mock"))


@pytest_asyncio.fixture
def lock():
    return RunLockService("")


@pytest_asyncio.fixture
def cancel():
    return CancelService("")


@pytest_asyncio.fixture
def policy(sessions):
    return PolicyEngine(sessions)


@pytest_asyncio.fixture
def audit(sessions):
    return AuditService(sessions)


@pytest_asyncio.fixture
def rate_limiter():
    return RateLimiter("", default_limit=100, default_window_s=60)


@pytest_asyncio.fixture
def knowledge_service(sessions):
    return KnowledgeService(KnowledgeStore(sessions), HashEmbedding())


@pytest_asyncio.fixture
def graph_service(sessions):
    return GraphService(GraphStore(sessions))


@pytest_asyncio.fixture
def tool_runtime(registry, policy, audit, rate_limiter, store, knowledge_service, graph_service):
    reg = default_registry()
    register_knowledge_tool(reg, knowledge_service)
    register_graph_tool(reg, graph_service)
    return ToolRuntime(registry=reg, policy=policy, audit=audit, limiter=rate_limiter, idem=store)


@pytest_asyncio.fixture
def deps(store, registry, gateway, lock, cancel, tool_runtime):
    return RuntimeDeps(
        store=store, registry=registry, gateway=gateway, lock=lock, cancel=cancel, tool_runtime=tool_runtime
    )
