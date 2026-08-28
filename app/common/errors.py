"""统一错误体系（§33 的 MVP 子集）。

原则：每个错误都有稳定 code、可观测 message、可结构化 detail。
API 层把 AgentError 映射为 {code, message, detail} 响应。
"""


class AgentError(Exception):
    code = "AGENT_ERROR"

    def __init__(self, message: str, *, code: str | None = None, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.detail = detail or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "detail": self.detail}

    def __str__(self) -> str:  # noqa: D105
        return f"[{self.code}] {self.message}"


class InvalidStateTransition(AgentError):
    code = "INVALID_STATE_TRANSITION"


class RunCancelledError(AgentError):
    code = "RUN_CANCELLED"


class BudgetExceededError(AgentError):
    code = "BUDGET_EXCEEDED"


class AgentTimeoutError(AgentError):
    code = "AGENT_TIMEOUT"


class LoopDetectedError(AgentError):
    code = "AGENT_LOOP_DETECTED"


class ModelError(AgentError):
    code = "MODEL_ERROR"


class ModelTimeoutError(ModelError):
    code = "MODEL_TIMEOUT"


class ModelRateLimitError(ModelError):
    code = "MODEL_RATE_LIMIT"


class ToolError(AgentError):
    code = "TOOL_ERROR"


class ToolNotFoundError(ToolError):
    code = "TOOL_NOT_FOUND"


class ToolInvalidArgumentError(ToolError):
    code = "TOOL_INVALID_ARGUMENT"


class ToolPermissionDeniedError(ToolError):
    code = "TOOL_PERMISSION_DENIED"


class ToolExecutionFailedError(ToolError):
    code = "TOOL_EXECUTION_FAILED"


class ToolTimeoutError(ToolError):
    """§29 工具执行超时（ToolDefinition.timeout_s 触发）。"""

    code = "TOOL_TIMEOUT"


class QueueFullError(AgentError):
    """§9.3 队列容量超限（Admission Control）。"""

    code = "QUEUE_FULL"


class ToolRateLimitedError(ToolError):
    code = "TOOL_RATE_LIMITED"


class ApprovalRequiredError(ToolError):
    code = "APPROVAL_REQUIRED"


class RecoveryAbandonedError(AgentError):
    code = "RECOVERY_ABANDONED"
