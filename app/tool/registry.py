"""Tool Registry + 执行管线（§4.4 的 MVP 子集）。

MVP 阶段：纯计算工具（READ）+ 带 SSRF 防护的 http.get；无沙箱/审批；
安全闸（权限/校验/幂等/审计）已接入 ToolRuntime 全管线。
"""

import asyncio
import http.client
import inspect
import ipaddress
import random
import socket
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import jsonschema

from app.common.cancellation import CancellationToken, await_cancelable
from app.common.contracts import Subject
from app.common.errors import (
    RunCancelledError,
    ToolError,
    ToolExecutionFailedError,
    ToolInvalidArgumentError,
    ToolNotFoundError,
    ToolPermissionDeniedError,
    ToolTimeoutError,
)


@dataclass(frozen=True)
class ToolDefinition:
    ref: str
    description: str
    input_schema: dict
    fn: Callable[..., Any]
    risk_level: str = "READ"  # READ / LOW_RISK_WRITE / HIGH_RISK_WRITE / CRITICAL
    permission: str = ""  # 所需权限点（Policy 判定用）
    version: str = "1"
    # 是否可并行执行（默认 true）；依赖工具用 deps 声明串行（§11.6）
    deps: list[str] = field(default_factory=list)
    # 需要运行时注入主体身份（fn(subject=subject, **args)），供检索类工具做租户过滤
    context_aware: bool = False
    # §6.5 Secret Reference：工具声明所需凭据 ref，真实值由 ToolRuntime 执行时注入（LLM 不可见）
    credential_ref: str = ""
    # §6.3 工具级超时（秒，None=不限）；执行失败重试次数（带抖动退避）
    timeout_s: float | None = None
    retry: int = 0

    def to_llm_schema(self) -> dict:
        return {
            "name": self.ref,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolResult:
    def __init__(self, *, ok: bool, data: Any = None, error: dict | None = None):
        self.ok = ok
        self.data = data
        self.error = error

    def to_dict(self) -> dict:
        return {"ok": self.ok, "data": self.data, "error": self.error}


class IdempotencyStore:
    """幂等存储接口（§4.7）：同 call_id 重放返回缓存结果。"""

    async def get(self, call_id: str) -> ToolResult | None:  # pragma: no cover - interface
        raise NotImplementedError

    async def set(self, call_id: str, result: ToolResult) -> None:  # pragma: no cover
        raise NotImplementedError


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.ref in self._tools:
            raise ValueError(f"tool already registered: {tool.ref}")
        self._tools[tool.ref] = tool

    def unregister(self, ref: str) -> bool:
        """注销工具（MCP server 移除/停用时清理其代理工具）。"""
        return self._tools.pop(ref, None) is not None

    def resolve(self, ref: str) -> ToolDefinition:
        tool = self._tools.get(ref)
        if tool is None:
            raise ToolNotFoundError(f"tool not found: {ref}")
        return tool

    def schemas(self) -> list[dict]:
        return [t.to_llm_schema() for t in self._tools.values()]

    def list(self) -> list[ToolDefinition]:
        return list(self._tools.values())


# ---------------- 内置工具 ----------------
def _calc_add(a: int, b: int) -> int:
    return a + b


def _echo(text: str) -> str:
    return text


# ---------------- http.get（带 SSRF 防护，§38 SSRF + §23.4 端口白名单） ----------------
def _is_ssrf_blocked(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast


def _resolve_host(host: str) -> list[str]:
    try:
        return list({info[4][0] for info in socket.getaddrinfo(host, None)})
    except socket.gaierror:
        return []


def _fetch_pinned(
    host: str, port: int, target_ip: str, path: str, scheme: str, timeout_s: int
) -> tuple[int, str, str]:
    """单次解析后固定到已验证 IP 连接（杜绝 DNS 重绑定 TOCTOU）；https 的 SNI/Host 仍用原 host。"""
    if scheme == "https":
        ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(host, port, timeout=timeout_s, context=ctx)
        conn._create_connection = lambda *a, **k: socket.create_connection(
            (target_ip, port), timeout=timeout_s
        )
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout_s)
        conn._create_connection = lambda *a, **k: socket.create_connection(
            (target_ip, port), timeout=timeout_s
        )
    try:
        conn.request(
            "GET", path, headers={"Host": host, "User-Agent": "agent-platform-http.get/1.0", "Accept": "*/*"}
        )
        resp = conn.getresponse()
        body = resp.read(4000).decode("utf-8", errors="replace")
        return resp.status, resp.headers.get("content-type", ""), body[:2000]
    finally:
        conn.close()


def _make_http_get(allowed_ports: set[int] | None = None):
    """构造 http.get 工具：allowed_ports 为空集合/None 则不限端口（SSRF 内网拦截仍在）。"""

    async def _http_get(url: str, timeout_s: int = 8) -> dict:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ToolInvalidArgumentError("http.get 只允许 http/https URL")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if allowed_ports and port not in allowed_ports:
            raise ToolInvalidArgumentError(f"http.get 端口被沙箱拦截: {port}")
        host = parsed.hostname or ""
        resolved = _resolve_host(host)
        if not resolved:
            raise ToolInvalidArgumentError(f"http.get 无法解析主机: {host}")
        if any(_is_ssrf_blocked(ip) for ip in resolved):
            raise ToolInvalidArgumentError(f"http.get 被 SSRF 防护拦截: {host} -> {resolved}")
        # 固定到已验证 IP 发起请求：不再二次 DNS 解析，校验期/连接期一致，杜绝 TOCTOU
        target_ip = resolved[0]
        path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
        status, content_type, body = await asyncio.to_thread(
            _fetch_pinned, host, port, target_ip, path, parsed.scheme, timeout_s
        )
        return {"status": status, "content_type": content_type, "body": body}

    return _http_get


def default_registry(http_allowed_ports: set[int] | None = None) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        ToolDefinition(
            ref="calc.add",
            description="对两个整数求和。",
            input_schema={
                "type": "object",
                "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                "required": ["a", "b"],
            },
            fn=_calc_add,
            permission="calc:add",
        )
    )
    reg.register(
        ToolDefinition(
            ref="echo",
            description="原样返回输入文本（测试用）。",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string", "maxLength": 1000}},
                "required": ["text"],
            },
            fn=_echo,
            permission="echo",
        )
    )
    reg.register(
        ToolDefinition(
            ref="http.get",
            description="发起 HTTP GET 请求（外网；内网地址被 SSRF 防护拦截）。",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "format": "uri"},
                    "timeout_s": {"type": "integer", "minimum": 1, "maximum": 30},
                },
                "required": ["url"],
            },
            fn=_make_http_get(http_allowed_ports),
            permission="http:get",
        )
    )
    return reg


async def execute_tool(
    tool: ToolDefinition,
    args: dict,
    *,
    call_id: str,
    subject: Subject,
    idem: IdempotencyStore,
    is_allowed: Callable[[Subject, str], bool] | None = None,
    token: CancellationToken | None = None,
) -> ToolResult:
    """§4.4 执行管线（MVP）：权限 → 参数校验 → 幂等 → 执行 → 返回。"""
    # 3 权限（默认允许；生产接 PolicyEngine）
    if is_allowed is not None and tool.permission and not is_allowed(subject, tool.permission):
        raise ToolPermissionDeniedError(f"permission denied: {tool.permission}")

    # 8 幂等：同 call_id 直接返回缓存
    cached = await idem.get(call_id)
    if cached is not None:
        return cached

    # 4 参数校验（JSON Schema）
    try:
        jsonschema.validate(args, tool.input_schema)
    except jsonschema.ValidationError as exc:
        raise ToolInvalidArgumentError(
            f"invalid args for {tool.ref}", detail={"reason": exc.message}
        ) from exc

    # 9 执行（纯函数丢线程池；异步工具在途可取消 §8.2；工具级超时/重试 §6.3）
    if token is not None and token.cancelled:
        raise RunCancelledError("cancelled before tool execution")

    async def _run_once():
        if tool.context_aware:
            # 检索类工具需要主体身份（租户过滤在服务端，§15.6）
            return await await_cancelable(tool.fn(subject=subject, **args), token)
        if inspect.iscoroutinefunction(tool.fn):
            return await await_cancelable(tool.fn(**args), token)
        return await asyncio.to_thread(tool.fn, **args)

    data: Any = None
    for attempt in range(tool.retry + 1):
        try:
            if tool.timeout_s is not None:
                data = await asyncio.wait_for(_run_once(), timeout=tool.timeout_s)
            else:
                data = await _run_once()
            result = ToolResult(ok=True, data=data)
            break
        except RunCancelledError:
            raise  # 取消：保留 CANCELLED 语义，不让外层误判为工具失败
        except ToolTimeoutError:
            raise
        except TimeoutError:
            raise ToolTimeoutError(f"tool {tool.ref} timed out after {tool.timeout_s}s") from None
        except ToolExecutionFailedError:
            if attempt < tool.retry:
                await asyncio.sleep(0.1 * (2**attempt) + random.uniform(0, 0.02 * (2**attempt)))
                continue
            raise
        except ToolError:
            raise  # 工具自身抛出的业务/安全错误（如 SSRF 拦截）原样透传，不重试
        except Exception as exc:
            if attempt < tool.retry:
                await asyncio.sleep(0.1 * (2**attempt) + random.uniform(0, 0.02 * (2**attempt)))
                continue
            raise ToolExecutionFailedError(f"tool {tool.ref} failed: {exc}") from exc

    # 缓存结果（幂等窗口由外层 TTL 控制）
    await idem.set(call_id, result)
    return result
