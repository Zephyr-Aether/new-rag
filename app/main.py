"""FastAPI 应用装配（Phase 0 工程基础设施 + Phase 1 Runtime 挂载）。

启动：settings → OTel → DB(engine/sessions) → 建表 → 种子 → 依赖容器 → 路由。
健康：/health/live（进程存活）/ /health/ready（依赖就绪）。
"""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.agent.api import runs, sessions
from app.agent.model import api as model_api
from app.agent.model.gateway import ModelGateway
from app.agent.runtime.budget import ExecutionBudget
from app.agent.runtime.cancel import CancelService
from app.agent.runtime.recovery import recover_stale_runs, resume_stale_runs
from app.agent.runtime.runtime import RuntimeDeps, execute_run
from app.agent.runtime.store import RunStore
from app.approval import api as approval_api
from app.approval.service import ApprovalService
from app.common.contracts import RunInput
from app.common.errors import AgentError
from app.configcenter import api as config_api
from app.configcenter.service import ConfigService, FlagService
from app.cost import api as cost_api
from app.cost.service import CostService
from app.data import api as data_api
from app.data.service import DataLifecycleService
from app.evaluation import api as eval_api
from app.evaluation.service import EvaluationService
from app.events import api as events_api
from app.events.service import EventOutbox
from app.gateway import auth_api, secrets_api, tenants_api, users_api
from app.gateway.oidc import OidcTenantMapper, OidcVerifier
from app.graph import api as graph_api
from app.graph.extract import make_graph_extractor
from app.graph.service import GraphService, register_graph_tool
from app.graph.store import GraphStore
from app.knowledge import api as knowledge
from app.knowledge.cache import make_retrieval_cache
from app.knowledge.embedding import EmbeddingCache, make_embedding
from app.knowledge.retrieval import KnowledgeService, register_knowledge_tool
from app.knowledge.store import KnowledgeStore
from app.knowledge.upload import UploadManager
from app.mcp import parse_mcp_allowlist, parse_mcp_servers
from app.mcp.api import router as mcp_api
from app.mcp.service import McpManager
from app.memory import api as memory_api
from app.memory.service import MemoryService
from app.memory.store import MemoryStore
from app.notification import make_notification_service
from app.observability.otel import setup_otel
from app.observability.payloads import TracePayloadRecorder
from app.queue import api as queue_api
from app.queue.queue import JobQueue
from app.queue.schema import migrate_agent_run_payload
from app.queue.store import JobStore
from app.release import api as release_api
from app.release.service import ReleaseService
from app.sandbox import SandboxConfig
from app.security.audit import AuditService
from app.security.audit_api import router as audit_api
from app.security.policy import PolicyEngine
from app.security.policy_api import router as policy_api
from app.security.roles_api import router as roles_api
from app.security.secrets import SecretManager
from app.settings import Settings, get_settings
from app.state import AppState
from app.storage.db import create_all, create_engine_and_sessions
from app.storage.lock import RunLockService
from app.storage.seed import seed_defaults
from app.tool import api as tools
from app.tool.custom import CustomToolManager, CustomToolSandbox
from app.tool.custom_api import router as custom_tools_api
from app.tool.limiter import RateLimiter
from app.tool.registry import default_registry
from app.tool.runtime import ToolRuntime
from app.ui import router as ui_router

logger = logging.getLogger("agent-platform")


async def _alembic_upgrade_if_managed(engine) -> None:
    """§57.4：库存在 alembic_version（alembic 管理）时启动自动 upgrade head。

    create_all 新建的库（无 alembic_version）跳过——其 schema 已由 create_all 保证。
    """
    from sqlalchemy import inspect

    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    if "alembic_version" not in tables:
        return
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    await asyncio.to_thread(command.upgrade, cfg, "head")


async def _ensure_columns(engine, additions: dict[str, list[tuple[str, str]]], dialect: str) -> None:
    """create_all 管理的库不会自动补新列：启动幂等 ADD COLUMN（生产 alembic，这里是开发库兜底）。"""
    async with engine.begin() as conn:
        for table, cols in additions.items():
            if dialect == "sqlite":
                row = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
                existing = {r[1] for r in row.fetchall()}
                for name, ddl in cols:
                    if name not in existing:
                        await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            else:
                for name, ddl in cols:
                    await conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {ddl}")


# Phase 1 身份/隔离字段（create_all 新库 schema 已含，这里只兜底已存在的旧库）
_IDENTITY_ADDITIONS = {
    "sqlite": {
        "users": [
            ("enabled", "BOOLEAN NOT NULL DEFAULT 1"),
            ("must_change_password", "BOOLEAN NOT NULL DEFAULT 0"),
        ],
        "upload_sessions": [("tenant_id", "VARCHAR(64) NOT NULL DEFAULT ''")],
        "sessions": [("title", "VARCHAR(255) NOT NULL DEFAULT ''")],
        "messages": [("docs_json", "TEXT NOT NULL DEFAULT '[]'")],
        "agent_versions": [("release_json", "TEXT NOT NULL DEFAULT '{}'")],
    },
    "postgresql": {
        "users": [
            ("enabled", "BOOLEAN NOT NULL DEFAULT true"),
            ("must_change_password", "BOOLEAN NOT NULL DEFAULT false"),
        ],
        "upload_sessions": [("tenant_id", "VARCHAR(64) NOT NULL DEFAULT ''")],
        "sessions": [("title", "VARCHAR(255) NOT NULL DEFAULT ''")],
        "messages": [("docs_json", "TEXT NOT NULL DEFAULT '[]'")],
        "agent_versions": [("release_json", "TEXT NOT NULL DEFAULT '{}'")],
    },
}


def _http_status_for(code: str) -> int:
    if code.startswith("TOOL_PERMISSION") or code in {"POLICY_DENIED", "PERMISSION_DENIED"}:
        return 403
    if code in {"AUTH_REQUIRED", "AUTH_INVALID_TOKEN", "AUTH_INVALID_CREDENTIALS"}:
        return 401
    if code in {"AUTH_NO_TENANT", "AUTH_DISABLED"}:
        return 403
    if code in {
        "RUN_NOT_FOUND",
        "AGENT_NOT_FOUND",
        "AGENT_VERSION_NOT_FOUND",
        "APPROVAL_NOT_FOUND",
        "SECRET_NOT_FOUND",
        "MEMORY_NOT_FOUND",
        "REGRESSION_NOT_FOUND",
        "DOCUMENT_NOT_FOUND",
        "ROLE_NOT_FOUND",
        "USER_NOT_FOUND",
        "UPLOAD_NOT_FOUND",
        "SESSION_NOT_FOUND",
        "MESSAGE_NOT_FOUND",
    }:
        return 404
    if code in {
        "BUDGET_EXCEEDED",
        "AGENT_TIMEOUT",
        "MODEL_TIMEOUT",
        "TOOL_RATE_LIMITED",
        "MODEL_RATE_LIMIT",
        "TENANT_RUN_QUOTA",
    }:
        return 429
    if code.endswith("_INVALID_ARGUMENT") or code in {
        "BAD_REQUEST",
        "USER_EXISTS",
        "TENANT_EXISTS",
        "UPLOAD_TOO_LARGE",
        "UPLOAD_INCOMPLETE",
        "INVALID_STATE_TRANSITION",
        "RELEASE_FLOW_TERMINATED",
        "RELEASE_CONTRACT_FAILED",
        "RELEASE_REGRESSION_FAILED",
        "MEMORY_POISONED",
        "MEMORY_SENSITIVE",
    }:
        return 400
    if code in {"TOOL_BREAKER_OPEN", "TOOL_TIMEOUT_UNKNOWN"}:
        return 503
    if code == "TOOL_TIMEOUT":
        return 504
    return 500


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO, format="%(levelname)s %(name)s %(message)s"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_otel(settings)
        engine, sessions = create_engine_and_sessions(settings.database_url)
        # §Phase 0 生产启动预检：fail-fast，缺 DB/Redis/LLM/认证配置直接阻断并列出缺失项
        from app.common.preflight import preflight_or_raise

        await preflight_or_raise(settings)
        # §57.4 迁移优先：alembic 管理的库先 upgrade head（避免 create_all 先建表，
        # 导致待执行迁移重复建表冲突）；create_all 新库/测试库无 alembic_version，跳过
        if settings.environment != "test":
            await _alembic_upgrade_if_managed(engine)
        await create_all(engine)
        # 开发库（create_all 管理）：幂等补新列（不 ALTER 已有表）；生产走 alembic
        if settings.database_url.startswith("sqlite"):
            await _ensure_columns(engine, _IDENTITY_ADDITIONS["sqlite"], "sqlite")
        elif settings.database_url.startswith("postgresql"):
            await _ensure_columns(engine, _IDENTITY_ADDITIONS["postgresql"], "postgresql")
        async with sessions() as session:
            seed = await seed_defaults(session, settings.seed_tenant, settings.seed_user)
        allowed_ports = {int(p) for p in settings.sandbox_allowed_ports.split(",") if p.strip().isdigit()}
        registry = default_registry(http_allowed_ports=allowed_ports or None)
        config_service = ConfigService(sessions)
        # §8 运行时模型配置：从配置中心恢复（页面配置优先于 .env）——先读，供 embedding / 网关使用
        saved_model = await config_service.get(tenant_id="", scope="MODEL", scope_id="default", key="config")
        model_cfg = (saved_model or {}).get("value") or {}
        # embedding 跟随运行时模型配置：真实 LLM 提供语义向量；无配置回落本地 hash 伪向量
        embed_settings = Settings(
            llm_provider=model_cfg.get("provider") or settings.llm_provider,
            llm_base_url=model_cfg.get("base_url") or settings.llm_base_url,
            llm_api_key=model_cfg.get("api_key") or settings.llm_api_key,
            embedding_model=settings.embedding_model,
        )
        embedding = make_embedding(embed_settings)  # §15 知识库 + §12 记忆共用同一 embedding
        knowledge_service = KnowledgeService(
            KnowledgeStore(sessions, shard_count=settings.knowledge_shard_count),
            embedding,
            cache=make_retrieval_cache(settings.redis_url),  # §49.6 有 Redis 走跨实例缓存
        )
        register_knowledge_tool(registry, knowledge_service)
        # §15.5 多知识库：确保默认库行存在
        try:
            await knowledge_service.store.ensure_default_base(settings.seed_tenant)
        except Exception:  # noqa: BLE001
            logger.warning("ensure default kb failed", exc_info=True)
        graph_service = GraphService(GraphStore(sessions))
        register_graph_tool(registry, graph_service)
        upload_manager = UploadManager(
            sessions, max_bytes=settings.max_upload_bytes
        )  # §15.7 知识库分片上传（分片存库）
        gateway = ModelGateway(settings)
        graph_extractor = make_graph_extractor(gateway)  # §16 接真 LLM 抽取（不可解析回落规则）
        # §23 pgvector：Postgres 启动建 vector 扩展 + HNSW 索引（SQLite 为 no-op）
        await knowledge_service.store.setup_pgvector()
        policy = PolicyEngine(sessions)
        audit = AuditService(sessions)
        rate_limiter = RateLimiter(settings.redis_url)
        store = RunStore(sessions)
        approvals = ApprovalService(sessions)
        release = ReleaseService(sessions, registry=registry, settings=settings)
        cost_service = CostService(sessions, settings=settings)
        # §8 运行时模型配置已在上方读取（model_cfg），这里配置网关
        if model_cfg:
            try:
                gateway.configure(
                    provider=model_cfg.get("provider", "mock"),
                    model=model_cfg.get("model", ""),
                    base_url=model_cfg.get("base_url", ""),
                    api_key=model_cfg.get("api_key", "") or None,
                )
            except Exception:  # noqa: BLE001
                logger.warning("model config from store invalid, using .env")
        # §7.3 MCP 页面接入：从配置中心读取 server 配置并热注册；无配置时回落 .env 初始配置
        mcp_allow = parse_mcp_allowlist(settings.mcp_tool_allowlist)
        mcp_manager = McpManager(registry, sessions, settings.seed_tenant, settings.mcp_max_output_chars)
        saved_mcp = await config_service.get(tenant_id="", scope="MCP", scope_id="default", key="servers")
        mcp_cfg = (saved_mcp or {}).get("value") or {}
        if not isinstance(mcp_cfg, dict) or not mcp_cfg:
            mcp_cfg = {
                name: {"base_url": url, "allow": list(mcp_allow.get(name) or []), "enabled": True}
                for name, url in parse_mcp_servers(settings.mcp_servers).items()
            }
        if mcp_cfg:
            try:
                await mcp_manager.reconcile(mcp_cfg)
            except Exception:  # noqa: BLE001
                logger.warning("mcp reconcile failed", exc_info=True)
        # 自定义沙箱代码工具：从配置中心读取定义并热注册
        custom_tool_manager = CustomToolManager(
            registry,
            sessions,
            settings.seed_tenant,
            sandbox=CustomToolSandbox(
                use_docker=settings.sandbox_docker,
                docker_runtime=settings.sandbox_docker_runtime,  # §23.4 gVisor："runsc"
            ),
        )
        saved_custom = await config_service.get(
            tenant_id="", scope="CUSTOM_TOOLS", scope_id="default", key="defs"
        )
        custom_defs = (saved_custom or {}).get("value") or []
        if isinstance(custom_defs, list) and custom_defs:
            try:
                await custom_tool_manager.reconcile(custom_defs)
            except Exception:  # noqa: BLE001
                logger.warning("custom tool reconcile failed", exc_info=True)
        flag_service = FlagService(sessions)
        evaluation_service = EvaluationService(sessions)
        # 评测样例配置化导入（§20：从页面配置中心 upsert；失败不阻断启动）
        try:
            seed_saved = await config_service.get(
                tenant_id="", scope="EVAL", scope_id="default", key="seed_cases"
            )
            seed_items = (seed_saved or {}).get("value") or []
            if seed_items:
                await evaluation_service.seed_cases(tenant_id=settings.seed_tenant, items=seed_items)
        except Exception:  # noqa: BLE001
            logger.warning("eval seed failed", exc_info=True)
        data_lifecycle = DataLifecycleService(sessions)
        event_outbox = EventOutbox(sessions)
        memory_service = MemoryService(
            MemoryStore(sessions), embedding=embedding, embedding_cache=EmbeddingCache()
        )
        secret_manager = SecretManager(
            sessions, key_source=settings.secret_encryption_key or settings.auth_jwt_secret
        )
        await secret_manager.load_all()  # §6.5 启动加载已加密密钥到缓存
        tool_runtime = ToolRuntime(
            registry=registry,
            policy=policy,
            audit=audit,
            limiter=rate_limiter,
            idem=store,
            approvals=approvals,
            notifier=make_notification_service(settings),
            secret_manager=secret_manager,
            sandbox=SandboxConfig(  # §23.4 工具执行资源/出口限额
                max_output_bytes=settings.sandbox_max_output_bytes, allowed_ports=allowed_ports
            ),
        )
        job_store = JobStore(sessions)
        job_queue = JobQueue(job_store)
        payload_recorder = TracePayloadRecorder(sessions, rate=settings.trace_payload_rate)  # §17.3 采样存储
        oidc = OidcVerifier(settings) if settings.oidc_enabled else None
        oidc_tenant_mapper = OidcTenantMapper(settings) if settings.oidc_enabled else None
        instance_id = settings.instance_id or uuid.uuid4().hex  # §23 多区域 HA：实例身份
        state = AppState(
            settings=settings,
            sessions=sessions,
            store=store,
            registry=registry,
            gateway=gateway,
            lock=RunLockService(settings.redis_url),
            cancel=CancelService(settings.redis_url),
            policy=policy,
            audit=audit,
            rate_limiter=rate_limiter,
            tool_runtime=tool_runtime,
            knowledge_service=knowledge_service,
            memory_service=memory_service,
            graph_service=graph_service,
            graph_extractor=graph_extractor,
            approvals=approvals,
            release=release,
            job_queue=job_queue,
            cost_service=cost_service,
            config_service=config_service,
            flag_service=flag_service,
            evaluation_service=evaluation_service,
            payload_recorder=payload_recorder,
            mcp_manager=mcp_manager,
            custom_tool_manager=custom_tool_manager,
            upload_manager=upload_manager,
            oidc=oidc,
            oidc_tenant_mapper=oidc_tenant_mapper,
            seed=seed,
            instance_id=instance_id,
            data_lifecycle=data_lifecycle,
            event_outbox=event_outbox,
            secret_manager=secret_manager,
        )
        app.state.agent = state
        # 启动恢复：无检查点的僵尸 Run 标 FAILED；有检查点的自动续跑（§8.4）
        recovered = await recover_stale_runs(state.store, state.lock)
        if recovered:
            logger.warning("recovered stale runs: %s", recovered)
        deps = RuntimeDeps(
            store=state.store,
            registry=state.registry,
            gateway=state.gateway,
            lock=state.lock,
            cancel=state.cancel,
            tool_runtime=state.tool_runtime,
            payload_recorder=state.payload_recorder,
            memory_service=state.memory_service,  # §12.4 记忆自动使用
        )
        resumed = await resume_stale_runs(state.store, state.lock, deps)
        if resumed:
            logger.info("auto-resumed stale runs: %s", resumed)

        # 异步 run 走队列（§9）：注册 agent_run handler 并启动 Worker
        async def _agent_run_handler(raw_payload: dict) -> None:
            # §57 队列消息 schema 演进：旧 payload 迁移到当前结构（新旧 Worker 共存）
            payload = migrate_agent_run_payload(raw_payload)
            run_input = RunInput(**payload["run_input"])
            await execute_run(
                run_input,
                deps,
                run_id=payload["run_id"],
                agent_version=payload["agent_version"],
                system_prompt=payload["system_prompt"],
                budget=ExecutionBudget(**payload["budget"]),
                release_status=payload.get("release_status"),
                frozen=payload.get("frozen_versions"),  # §22.1 版本冻结
                client_run_id=run_input.client_run_id,
            )
            from app.agent.api.sessions import persist_chat_messages

            await persist_chat_messages(state, payload["run_id"])  # §10 对话持久化

        job_queue.register("agent_run", _agent_run_handler)
        # §55 按任务类型分 Worker Pool（agent_run 独立池，防 ingest 等任务饿死在线请求）
        job_queue.start(workers_by_type={"agent_run": 2})
        # §11 队列深度定时采样：后台落库供"队列深度随时间"趋势（保留 24h）
        sampler_stop = asyncio.Event()

        async def _queue_sampler() -> None:
            while not sampler_stop.is_set():
                # 先等待一个间隔再采样，避免启动瞬间与其它写入并发竞争 StaticPool 连接
                try:
                    await asyncio.wait_for(sampler_stop.wait(), timeout=settings.queue_sample_interval_s)
                except TimeoutError:
                    pass
                if sampler_stop.is_set():
                    break
                try:
                    s = await job_queue.store.stats()
                    await job_queue.store.save_sample(s)
                except Exception:  # noqa: BLE001
                    logger.warning("queue sample failed", exc_info=True)

        sampler_task = asyncio.create_task(_queue_sampler())
        yield
        sampler_stop.set()
        await sampler_task
        await job_queue.stop()
        await mcp_manager.close()  # §7.3 关闭外部 MCP 连接
        await state.lock.close()
        await engine.dispose()

    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    # API 级幂等：POST/PUT/PATCH 携带 Idempotency-Key 时重放去重（§API-Idempotency）
    from app.gateway.idempotency import make_idempotency_middleware

    app.middleware("http")(make_idempotency_middleware())
    app.include_router(runs.router, prefix="/agents")
    app.include_router(sessions.router, prefix="/agents")
    app.include_router(tools.router)
    app.include_router(knowledge.router)
    app.include_router(memory_api.router)
    app.include_router(approval_api.router)
    app.include_router(release_api.router)
    app.include_router(graph_api.router)
    app.include_router(auth_api.router)
    app.include_router(users_api.router)
    app.include_router(tenants_api.router)
    app.include_router(secrets_api.router)
    app.include_router(cost_api.router)
    app.include_router(model_api.router)
    app.include_router(mcp_api)
    app.include_router(custom_tools_api)
    app.include_router(audit_api)
    app.include_router(policy_api)
    app.include_router(roles_api)
    app.include_router(config_api.router)
    app.include_router(eval_api.router)
    app.include_router(ui_router.router)
    app.include_router(data_api.router)
    app.include_router(events_api.router)
    app.include_router(queue_api.router)

    @app.get("/health/live")
    async def health_live() -> dict:
        return {"status": "alive"}

    @app.get("/health/ready")
    async def health_ready(request: Request) -> dict:
        # MVP Readiness：依赖容器已就绪即通过；LLM 挂掉不杀进程（§56.4）
        state = getattr(request.app.state, "agent", None)
        return {"status": "ready" if state else "not_ready"}

    @app.get("/health/ha")
    async def health_ha(request: Request) -> dict:
        """§23 多区域 HA 最小切片：实例身份/就绪/队列排空（复制/容灾超出 MVP）。"""
        state = getattr(request.app.state, "agent", None)
        if state is None:
            return {"ready": False, "role": "primary"}
        return {
            "instance_id": state.instance_id,
            "region": state.settings.region,
            "role": "primary",
            "ready": True,
            "queue_watermark": round(state.job_queue.watermark(), 3),
            "queue_drain_ok": not state.job_queue.is_backpressured(),
        }

    @app.get("/ha/status")
    async def ha_status(request: Request) -> dict:
        """多区域 HA 身份切片：region/role/实例/就绪。

        真复制/故障转移需多实例部署（超出单实例 MVP），本端点提供身份与就绪探测。
        """
        state = getattr(request.app.state, "agent", None)
        if state is None:
            return {"ready": False, "role": "primary"}
        return {
            "instance_id": state.instance_id,
            "region": state.settings.region,
            "role": "primary",
            "ready": True,
            "queue_watermark": round(state.job_queue.watermark(), 3),
            "note": "多区域 HA 需多实例部署；本仓库提供身份/就绪切片",
        }

    @app.get("/meta")
    async def meta(request: Request) -> dict:
        """前端上下文：seed agent/tenant（Release 页需知道操作哪个 agent）。"""
        state = getattr(request.app.state, "agent", None)
        if state is None:
            return {"ready": False}
        seed = state.seed
        return {
            "ready": True,
            "agent_id": seed["agent_id"],
            "agent_version": seed["agent_version"],
            "tenant_id": seed["tenant_id"],
        }

    @app.exception_handler(AgentError)
    async def on_agent_error(request: Request, exc: AgentError) -> JSONResponse:
        return JSONResponse(status_code=_http_status_for(exc.code), content=exc.to_dict())

    # 产品化前端：frontend/dist 存在则托管静态产物 + SPA fallback（API 路由已先注册，优先匹配）
    dist_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if (dist_dir / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str) -> Response:
            # 前端是 HashRouter：导航都在 #/ 内，真实请求路径只有根路径。
            # 其余未匹配的 GET 一律视为 API 路径，返回 JSON 404，不吐 index.html（避免吞掉 API 错误）。
            if full_path in ("", "index.html"):
                return FileResponse(dist_dir / "index.html")
            return JSONResponse(
                status_code=404,
                content={"code": "NOT_FOUND", "message": f"path not found: /{full_path}"},
            )

    return app


app = create_app()
