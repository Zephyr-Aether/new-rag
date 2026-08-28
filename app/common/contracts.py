"""跨层共享的契约（Pydantic），对应设计文档中的数据结构。

这些是模块间边界：Agent Runtime / Model Gateway / Tool Runtime / API 共用。
变更必须走版本演进（§2.1 契约即边界）。
"""

from contextvars import ContextVar
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

# §60 Replay 换检索参数：Runtime 按 Run 设置，kb.search 优先读它（覆盖 LLM 给的 k）
RETRIEVAL_TOP_K: ContextVar[int | None] = ContextVar("retrieval_top_k", default=None)
# §22.1 版本冻结：Run 级冻结 knowledge_version，kb.search 检索用它（运行中不漂移，§49.5 缓存键含它）
RETRIEVAL_KNOWLEDGE_VERSION: ContextVar[str | None] = ContextVar("retrieval_knowledge_version", default=None)


class Subject(BaseModel):
    """请求主体身份（认证后注入，贯穿全链路，§53.1）。"""

    tenant_id: str
    user_id: str


class RunInput(BaseModel):
    tenant_id: str
    user_id: str
    agent_id: str
    session_id: str
    text: str
    model: str | None = None  # 覆盖默认模型
    retrieval_top_k: int | None = None  # 检索 top_k 覆盖（§60 Replay 换检索参数）
    history: list[dict] | None = None  # §10 历史轮次（近轮原文，旧轮由 runtime 压缩为摘要）


class RunResult(BaseModel):
    run_id: str
    tenant_id: str
    user_id: str
    agent_id: str
    agent_version: int
    session_id: str
    state: str
    answer: str | None = None
    steps: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost: Decimal = Decimal("0")
    error: dict | None = None


class ToolCallDraft(BaseModel):
    """LLM 输出的原始工具意图（§11.2）。"""

    id: str
    name: str
    arguments: str = ""  # JSON 字符串，需解析校验


class ModelResult(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCallDraft] = Field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost: Decimal = Decimal("0")
    model: str = ""


class LLMRecord(BaseModel):
    """一次 LLM 调用的完整记录（§50.1 归因最小单元）。"""

    model: str
    messages_json: str
    content: str | None = None
    tool_calls: list[ToolCallDraft] = Field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost: Decimal = Decimal("0")
    latency_ms: int = 0


class ToolCallRequest(BaseModel):
    """规范化的工具执行请求（§4.2），跨 Agent Runtime / Tool Runtime / API 共用。"""

    call_id: str  # 幂等键
    tenant_id: str
    user_id: str
    tool_ref: str
    args: dict = Field(default_factory=dict)
    run_id: str = ""
    step_id: str = ""
    trace_id: str = ""


class ToolCallResult(BaseModel):
    """工具执行结果（§4.2）。"""

    call_id: str
    ok: bool
    data: Any | None = None
    error: dict | None = None
    latency_ms: int = 0
    decision: dict | None = None  # 权限/限流/审批决策链（审计用）
