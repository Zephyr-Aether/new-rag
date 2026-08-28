"""应用级依赖容器（挂在 app.state 上，供路由访问）。"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agent.model.gateway import ModelGateway
from app.agent.runtime.cancel import CancelService
from app.agent.runtime.store import RunStore
from app.approval.service import ApprovalService
from app.configcenter.service import ConfigService, FlagService
from app.cost.service import CostService
from app.data.service import DataLifecycleService
from app.evaluation.service import EvaluationService
from app.events.service import EventOutbox
from app.gateway.oidc import OidcTenantMapper, OidcVerifier
from app.graph.extract import GraphExtractor
from app.graph.service import GraphService
from app.knowledge.retrieval import KnowledgeService
from app.knowledge.upload import UploadManager
from app.mcp.service import McpManager
from app.memory.service import MemoryService
from app.observability.payloads import TracePayloadRecorder
from app.queue.queue import JobQueue
from app.release.service import ReleaseService
from app.security.audit import AuditService
from app.security.policy import PolicyEngine
from app.security.secrets import SecretManager
from app.settings import Settings
from app.storage.lock import RunLockService
from app.tool.custom import CustomToolManager
from app.tool.limiter import RateLimiter
from app.tool.registry import ToolRegistry
from app.tool.runtime import ToolRuntime


@dataclass
class AppState:
    settings: Settings
    sessions: async_sessionmaker
    store: RunStore
    registry: ToolRegistry
    gateway: ModelGateway
    lock: RunLockService
    cancel: CancelService
    policy: PolicyEngine
    audit: AuditService
    rate_limiter: RateLimiter
    tool_runtime: ToolRuntime
    knowledge_service: KnowledgeService
    memory_service: MemoryService
    graph_service: GraphService
    graph_extractor: GraphExtractor
    approvals: ApprovalService
    release: ReleaseService
    job_queue: JobQueue
    cost_service: CostService
    config_service: ConfigService
    flag_service: FlagService
    evaluation_service: EvaluationService
    payload_recorder: TracePayloadRecorder
    seed: dict  # {tenant_id, user_id, agent_id, agent_version}
    mcp_manager: McpManager | None = None  # §7.3 页面接入的 MCP server 管理器
    custom_tool_manager: CustomToolManager | None = None  # 页面录入的沙箱代码工具
    upload_manager: UploadManager | None = None  # §15.7 知识库分片上传会话管理
    oidc: OidcVerifier | None = None
    oidc_tenant_mapper: OidcTenantMapper | None = None
    instance_id: str = "local"  # §23 多区域 HA：本实例身份
    data_lifecycle: DataLifecycleService | None = None  # §26 数据生命周期
    event_outbox: EventOutbox | None = None  # §28.2 事件 Outbox
    secret_manager: SecretManager | None = None  # §6.5 加密密钥（持久化）

    def deps(self):
        """构建 RuntimeDeps（审批/Replay 等需要执行 run 的地方复用，§19）。"""
        from app.agent.runtime.runtime import RuntimeDeps

        return RuntimeDeps(
            store=self.store,
            registry=self.registry,
            gateway=self.gateway,
            lock=self.lock,
            cancel=self.cancel,
            tool_runtime=self.tool_runtime,
            memory_service=self.memory_service,  # §12.4 记忆自动使用
        )
