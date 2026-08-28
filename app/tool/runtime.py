"""Tool Runtime 编排器（§4.4 全管线）。

管线：resolve → 权限(PolicyEngine) → 限流 → 风险闸(审批 seam) → 幂等 → 校验 → 执行 → 审计。
Agent Runtime 与 直接 API 都走这里，保证安全闸不被绕过。
"""

import time

from app.approval.service import ApprovalService
from app.common.cancellation import CancellationToken
from app.common.circuit_breaker import CircuitBreaker
from app.common.contracts import Subject, ToolCallRequest, ToolCallResult
from app.common.errors import (
    ApprovalRequiredError,
    RunCancelledError,
    ToolError,
    ToolExecutionFailedError,
    ToolPermissionDeniedError,
    ToolRateLimitedError,
    ToolTimeoutError,
)
from app.notification import NotificationService
from app.sandbox import SandboxConfig, serialize_size
from app.security.audit import AuditService
from app.security.policy import PolicyEngine
from app.security.secrets import SecretManager, inject_secret
from app.tool.limiter import RateLimiter
from app.tool.registry import IdempotencyStore, ToolRegistry, execute_tool

# 风险闸：达到这些等级必须审批（§19 落地审批流；无审批服务则直接拒）
DEFAULT_RISK_THRESHOLD = {"HIGH_RISK_WRITE", "CRITICAL"}


class ToolRuntime:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        policy: PolicyEngine,
        audit: AuditService,
        limiter: RateLimiter,
        idem: IdempotencyStore,
        risk_threshold: set[str] | None = None,
        approvals: ApprovalService | None = None,
        notifier: NotificationService | None = None,
        secret_manager: SecretManager | None = None,
        sandbox: SandboxConfig | None = None,
    ):
        self.registry = registry
        self.policy = policy
        self.audit = audit
        self.limiter = limiter
        self.idem = idem
        self.risk_threshold = risk_threshold if risk_threshold is not None else DEFAULT_RISK_THRESHOLD
        self.approvals = approvals
        self.notifier = notifier
        self.secret_manager = secret_manager
        self.sandbox = sandbox
        # §6.3 工具级熔断：每工具一个实例（执行失败计数，防下游故障拖垮）
        self._breakers: dict[str, CircuitBreaker] = {}

    def _breaker(self, ref: str) -> CircuitBreaker:
        brk = self._breakers.get(ref)
        if brk is None:
            brk = self._breakers[ref] = CircuitBreaker(name=f"tool:{ref}")
        return brk

    async def execute(
        self, call: ToolCallRequest, *, token: CancellationToken | None = None
    ) -> ToolCallResult:
        subject = Subject(tenant_id=call.tenant_id, user_id=call.user_id)
        started = time.monotonic()

        # §8.2 在途取消：已取消则不执行
        if token is not None and token.cancelled:
            raise RunCancelledError("cancelled before tool execution")

        # 1 resolve
        tool = self.registry.resolve(call.tool_ref)

        # 3 权限（PolicyEngine，默认拒绝）
        decision = await self.policy.is_allowed(subject, "tool:execute", tool.ref)
        await self.audit.record(
            tenant_id=call.tenant_id,
            actor_id=call.user_id,
            trace_id=call.trace_id,
            action="tool:execute",
            resource=tool.ref,
            resource_id=call.call_id,
            outcome="ALLOWED" if decision.allowed else "DENIED",
            detail={"policy_id": decision.policy_id, "reason": decision.reason},
        )
        if not decision.allowed:
            raise ToolPermissionDeniedError(
                f"permission denied: {tool.ref}",
                code="TOOL_PERMISSION_DENIED",
                detail={"policy_id": decision.policy_id, "reason": decision.reason},
            )

        # 6 限流（tenant:user:tool）
        limit_key = f"{call.tenant_id}:{call.user_id}:{tool.ref}"
        if not await self.limiter.acquire(limit_key):
            await self.audit.record(
                tenant_id=call.tenant_id,
                actor_id=call.user_id,
                trace_id=call.trace_id,
                action="tool:rate_limit",
                resource=tool.ref,
                resource_id=call.call_id,
                outcome="RATE_LIMITED",
            )
            raise ToolRateLimitedError(f"rate limited: {tool.ref}")

        # 5 风险闸（§19 审批流：按 call_id 幂等查审批——已批准放行、已拒绝拒绝、否则创建+抛 APPROVAL_REQUIRED）
        if tool.risk_level in self.risk_threshold:
            if self.approvals is None:
                raise ApprovalRequiredError(
                    f"approval required: {tool.ref}", detail={"risk_level": tool.risk_level}
                )
            existing = await self.approvals.find_for_call(
                tenant_id=call.tenant_id, call_id=call.call_id, tool_ref=tool.ref
            )
            if existing is not None and existing["status"] == "REJECTED":
                await self.audit.record(
                    tenant_id=call.tenant_id,
                    actor_id=call.user_id,
                    trace_id=call.trace_id,
                    action="tool:approval",
                    resource=tool.ref,
                    resource_id=call.call_id,
                    outcome="APPROVAL_REJECTED",
                    detail={"approval_id": existing["approval_id"], "risk_level": tool.risk_level},
                )
                raise ApprovalRequiredError(
                    f"approval rejected: {tool.ref}",
                    detail={
                        "approval_id": existing["approval_id"],
                        "risk_level": tool.risk_level,
                        "rejected": True,
                    },
                )
            if existing is None or existing["status"] != "APPROVED":
                approval_id = (
                    existing["approval_id"]
                    if existing is not None
                    else await self.approvals.create(
                        tenant_id=call.tenant_id,
                        requester_id=call.user_id,
                        tool_ref=tool.ref,
                        call_id=call.call_id,
                        risk_level=tool.risk_level,
                    )
                )
                await self.audit.record(
                    tenant_id=call.tenant_id,
                    actor_id=call.user_id,
                    trace_id=call.trace_id,
                    action="tool:approval",
                    resource=tool.ref,
                    resource_id=call.call_id,
                    outcome="APPROVAL_REQUIRED",
                    detail={"approval_id": approval_id, "risk_level": tool.risk_level},
                )
                if self.notifier is not None:  # §19 审批人通知
                    await self.notifier.notify(
                        tenant_id=call.tenant_id,
                        approval_id=approval_id,
                        tool_ref=tool.ref,
                        requester_id=call.user_id,
                    )
                raise ApprovalRequiredError(
                    f"approval required: {tool.ref}",
                    detail={"approval_id": approval_id, "risk_level": tool.risk_level},
                )
            # 已批准：放行继续执行（同一 call_id 不重复审批）

        # 4 + 8 + 9 校验 → 幂等 → 执行（含 SSRF/输出安全，在途可取消）
        # §6.3 工具级熔断：OPEN 时快速失败（不悬挂不重试）
        brk = self._breaker(tool.ref)
        if not brk.allow():
            raise ToolError(f"tool circuit breaker open: {tool.ref}", code="TOOL_BREAKER_OPEN")
        # §6.5 Secret Reference：工具声明 credential_ref => 真实凭据执行时注入（LLM 不可见）
        reset_secret = None
        if tool.credential_ref and self.secret_manager is not None:
            reset_secret = inject_secret(self.secret_manager.get(tool.credential_ref))
        try:
            result = await execute_tool(
                tool, call.args, call_id=call.call_id, subject=subject, idem=self.idem, token=token
            )
        except (ToolExecutionFailedError, ToolTimeoutError):
            brk.record(False)  # 执行级失败计熔断
            raise
        except ToolError:
            raise  # 参数/业务错误不算工具故障，不熔断
        except Exception:
            brk.record(False)
            raise
        finally:
            if reset_secret is not None:
                reset_secret()
        brk.record(result.ok)
        # §23.4 Sandbox：输出大小上限（防大 payload 撑爆 Context）
        if (
            self.sandbox is not None
            and result.ok
            and serialize_size(result.data) > self.sandbox.max_output_bytes
        ):
            raise ToolExecutionFailedError(
                f"tool output exceeds sandbox limit: {tool.ref}",
                detail={"max_output_bytes": self.sandbox.max_output_bytes},
            )
        latency_ms = int((time.monotonic() - started) * 1000)

        await self.audit.record(
            tenant_id=call.tenant_id,
            actor_id=call.user_id,
            trace_id=call.trace_id,
            action="tool:execute",
            resource=tool.ref,
            resource_id=call.call_id,
            outcome="SUCCEEDED" if result.ok else "FAILED",
            detail={"latency_ms": latency_ms},
        )
        return ToolCallResult(
            call_id=call.call_id,
            ok=result.ok,
            data=result.data,
            error=None if result.ok else result.error,
            latency_ms=latency_ms,
            decision={"policy_id": decision.policy_id, "risk_level": tool.risk_level},
        )
