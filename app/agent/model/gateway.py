"""ModelGateway：所有 LLM 调用的统一出口（§52.1 不允许 Agent → Provider 直连）。

Provider 接口：
    async def complete(messages: list[dict], tools: list[dict], model: str) -> ModelResult

- MockProvider：本地确定性模型，离线跑通整条管线（工具调用 → 观察 → 最终答案）。
- OpenAIProvider：OpenAI 兼容 /chat/completions（可指向 DeepSeek/Qwen/内部代理等）。
成本为估算单价（§50.1：estimated_cost），账单口径由对账层校正。
"""

import asyncio
import json
import re
import time
from abc import ABC, abstractmethod
from decimal import Decimal

import httpx
from opentelemetry import trace

from app.agent.model.health import ProviderHealth
from app.agent.model.pool import ModelProviderPool
from app.agent.model.router import ModelRouter
from app.agent.model.scheduler import ModelScheduler
from app.common.cancellation import CancellationToken, cancelable_sleep
from app.common.circuit_breaker import CircuitBreaker
from app.common.contracts import ModelResult, ToolCallDraft
from app.common.errors import ModelError, ModelRateLimitError, ModelTimeoutError, RunCancelledError
from app.settings import Settings
from app.tool.limiter import RateLimiter

_PLUS_RE = re.compile(r"(\d+)\s*\+\s*(\d+)")
_KB_RE = re.compile(r"(?:知识库|检索|kb)\s*[:：]?\s*(.+)")
_WORD_BOUNDARY = r"(?<![A-Za-z0-9_.])"


def _coerce_mock_arg(value: str, ptype: str):
    """按 schema 属性类型做粗粒度强转（mock 用，真 LLM 不需要）。"""
    if ptype == "integer":
        try:
            return int(value)
        except ValueError:
            return value
    if ptype == "number":
        try:
            return float(value)
        except ValueError:
            return value
    if ptype == "boolean":
        return value.lower() in ("true", "1", "yes")
    return value


def _mock_match_tool(last_user: str, tools: list[dict]):
    """mock 触发自定义/MCP 工具：用户消息提到工具名（可带 key=value 参数）即调用它。

    优先级：先按完整 ref（如 ext.weather），再按最后一段名（如 weather）。
    参数：优先解析 `key=value` 并按 schema 强转；否则把工具名后的剩余文本作为第一个必填参数。
    """
    if not tools:
        return None
    names = [t.get("name") for t in tools if isinstance(t, dict) and t.get("name")]
    hit = None
    for name in names:
        if re.search(rf"{_WORD_BOUNDARY}{re.escape(name)}(?![A-Za-z0-9_.])", last_user):
            hit = name
            break
    if hit is None:
        for name in names:
            seg = name.split(".")[-1]
            if seg and re.search(rf"{_WORD_BOUNDARY}{re.escape(seg)}(?![A-Za-z0-9_.])", last_user):
                hit = name
                break
    if hit is None:
        return None
    tool = next((t for t in tools if t.get("name") == hit), {})
    schema = tool.get("input_schema") or {}
    props = schema.get("properties") or {}
    kv = dict(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^\s,，；]+)", last_user))
    args = {}
    for k, v in kv.items():
        if k in props:
            args[k] = _coerce_mock_arg(
                v, (props[k].get("type") if isinstance(props[k], dict) else "") or "string"
            )
    if not args:
        required = schema.get("required") or []
        if required:
            after = re.split(rf"{re.escape(hit)}", last_user, maxsplit=1)[-1].strip()
            after = re.sub(r"^[\s，,。:：]+", "", after)
            if after:
                rtype = (
                    (props.get(required[0]) or {}).get("type")
                    if isinstance(props.get(required[0]), dict)
                    else ""
                )
                args[required[0]] = _coerce_mock_arg(after, rtype or "string")
    return hit, json.dumps(args, ensure_ascii=False)


class BaseProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str,
        token: CancellationToken | None = None,
    ) -> ModelResult: ...

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str,
        on_token=None,
        token: CancellationToken | None = None,
    ) -> ModelResult:
        """默认流式：无真实流式时一次性返回，content 整体回调 on_token（mock/兼容）。"""
        result = await self.complete(messages, tools, model, token=token)
        if on_token and result.content:
            await on_token(result.content)
        return result

    def estimate_cost(self, tokens_in: int, tokens_out: int) -> Decimal:
        return Decimal(
            (tokens_in / 1_000_000) * self.price_in + (tokens_out / 1_000_000) * self.price_out
        ).quantize(Decimal("0.000001"))


class MockProvider(BaseProvider):
    """确定性 mock：user 文本含 `a + b` 且无 tool 回执 => 返回 calc.add 工具调用；
    否则返回回显答案。用于离线演示/测试/CI。"""

    name = "mock"

    def __init__(self, price_in: float = 1.0, price_out: float = 3.0):
        self.price_in = price_in
        self.price_out = price_out

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str,
        token: CancellationToken | None = None,
    ) -> ModelResult:
        await cancelable_sleep(token, 0.01)  # 模拟延迟，可被取消中断
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        # 有工具回执 => 收敛为最终答案
        for m in reversed(messages[-4:]):
            if m.get("role") == "tool":
                data = str(m.get("content", ""))
                return ModelResult(
                    content=f"Answer: {data} (mock)",
                    tokens_in=len(messages),
                    tokens_out=len(data),
                    cost=self.estimate_cost(len(messages), len(data)),
                    model=model,
                )
        m = _PLUS_RE.search(last_user)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            args = f'{{"a": {a}, "b": {b}}}'
            return ModelResult(
                tool_calls=[ToolCallDraft(id="call_mock", name="calc.add", arguments=args)],
                tokens_in=len(messages),
                tokens_out=0,
                cost=self.estimate_cost(len(messages), 0),
                model=model,
            )
        kb = _KB_RE.search(last_user)
        if kb:
            query = kb.group(1).strip() or last_user
            args = json.dumps({"query": query, "k": 3}, ensure_ascii=False)
            return ModelResult(
                tool_calls=[ToolCallDraft(id="call_kb", name="kb.search", arguments=args)],
                tokens_in=len(messages),
                tokens_out=0,
                cost=self.estimate_cost(len(messages), 0),
                model=model,
            )
        # 自定义/MCP 工具：用户提到工具名即触发（如 `用 my.add a=3 b=4`、`ext.weather city=北京`）
        named = _mock_match_tool(last_user, tools)
        if named is not None:
            name, args = named
            return ModelResult(
                tool_calls=[ToolCallDraft(id=f"call_mock_{name}", name=name, arguments=args)],
                tokens_in=len(messages),
                tokens_out=0,
                cost=self.estimate_cost(len(messages), 0),
                model=model,
            )
        return ModelResult(
            content=f"Echo(mock): {last_user}",
            tokens_in=len(messages),
            tokens_out=len(last_user),
            cost=self.estimate_cost(len(messages), len(last_user)),
            model=model,
        )


class OpenAIProvider(BaseProvider):
    """OpenAI 兼容 chat completions。tools 转函数 schema，解析 tool_calls。"""

    name = "openai"

    def __init__(self, settings: Settings, transport=None):
        if not settings.llm_base_url:
            raise ModelError("APP_LLM_BASE_URL is required for provider=openai")
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key
        self.timeout_s = settings.llm_timeout_s
        self.price_in = settings.llm_price_input_per_mtok
        self.price_out = settings.llm_price_output_per_mtok
        self.transport = transport  # 测试注入 MockTransport；生产为 None

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str,
        token: CancellationToken | None = None,
    ) -> ModelResult:
        body: dict = {"model": model, "messages": messages}
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ]
            body["tool_choice"] = "auto"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            client = httpx.AsyncClient(timeout=self.timeout_s, transport=self.transport)
            req_task = asyncio.create_task(
                client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
            )
            if token is not None:
                # §8.2 在途取消：用户取消则中断 HTTP 请求（不再耗 token/连接/费用）
                wait_token = asyncio.create_task(token.wait())
                await asyncio.wait({req_task, wait_token}, return_when=asyncio.FIRST_COMPLETED)
                if token.cancelled:
                    req_task.cancel()
                    await client.aclose()
                    raise RunCancelledError("cancelled while awaiting LLM")
                wait_token.cancel()
                await asyncio.gather(wait_token, return_exceptions=True)
            resp = await req_task
            await client.aclose()
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError("LLM request timed out", detail={"model": model}) from exc
        if resp.status_code == 429:
            raise ModelRateLimitError("LLM rate limited", detail={"status": resp.status_code})
        if resp.status_code >= 400:
            raise ModelError(f"LLM provider error {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        choice = data["choices"][0]["message"]
        tool_calls = [
            ToolCallDraft(id=tc["id"], name=tc["function"]["name"], arguments=tc["function"]["arguments"])
            for tc in choice.get("tool_calls") or []
        ]
        usage = data.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens", 0))
        tokens_out = int(usage.get("completion_tokens", 0))
        return ModelResult(
            content=choice.get("content"),
            tool_calls=tool_calls,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=self.estimate_cost(tokens_in, tokens_out),
            model=model,
        )

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str,
        on_token=None,
        token: CancellationToken | None = None,
    ) -> ModelResult:
        """OpenAI 兼容流式：`stream:true`，content 增量回调 on_token；tool_calls 增量累积。"""
        body: dict = {"model": model, "messages": messages, "stream": True}
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ]
            body["tool_choice"] = "auto"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        content = ""
        acc: dict[int, dict] = {}
        async with httpx.AsyncClient(timeout=self.timeout_s, transport=self.transport) as client:
            async with client.stream(
                "POST", f"{self.base_url}/chat/completions", json=body, headers=headers
            ) as resp:
                if resp.status_code >= 400:
                    text = (await resp.aread()).decode()[:200]
                    if resp.status_code == 429:
                        raise ModelRateLimitError("LLM rate limited", detail={"status": resp.status_code})
                    raise ModelError(f"LLM provider error {resp.status_code}: {text}")
                async for line in resp.aiter_lines():
                    if token is not None and token.cancelled:
                        raise RunCancelledError("cancelled while streaming LLM")
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    if delta.get("content"):
                        content += delta["content"]
                        if on_token:
                            await on_token(delta["content"])
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]
        tool_calls = (
            [
                ToolCallDraft(id=a["id"] or f"call_{i}", name=a["name"], arguments=a["arguments"])
                for i, a in sorted(acc.items())
            ]
            if acc
            else []
        )
        tokens_in = tokens_out = 0  # 流式响应通常不含 usage（如需可加 stream_options）
        return ModelResult(
            content=content or None,
            tool_calls=tool_calls,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=self.estimate_cost(tokens_in, tokens_out),
            model=model,
        )


class ModelGateway:
    def __init__(self, settings: Settings, providers: list[BaseProvider] | None = None):
        self.settings = settings
        self.default_model = settings.llm_model
        self.provider = self._build_provider(settings)
        self._runtime_api_key: str | None = None
        self.pool = None
        if providers:
            self.pool = ModelProviderPool(providers)  # §52.1 多 Provider 按健康切流
            self.provider = providers[0]
        self.router = ModelRouter(settings)
        self.scheduler = ModelScheduler()  # §52 调度过滤管线（决策落 Trace）
        self.last_schedule_reason = ""  # §52 最近一次调度决策（Replay 对比用）
        self.breaker = CircuitBreaker(
            name=f"llm:{settings.llm_model}", failure_threshold=settings.llm_breaker_threshold
        )
        self.health = ProviderHealth()  # §52.3 滑动窗口健康（Degraded 降权 / Unavailable 剔除）
        self.limiter = RateLimiter(
            settings.redis_url,
            default_limit=settings.llm_rate_limit,
            default_window_s=settings.llm_rate_limit_window_s,
        )

    def _build_provider(self, settings: Settings) -> BaseProvider:
        if settings.llm_provider == "mock":
            return MockProvider(settings.llm_price_input_per_mtok, settings.llm_price_output_per_mtok)
        if settings.llm_provider == "openai":
            return OpenAIProvider(settings)
        raise ModelError(f"unknown provider: {settings.llm_provider}")

    def configure(
        self, *, provider: str, model: str = "", base_url: str = "", api_key: str | None = None
    ) -> None:
        """§8 运行时改模型配置：重建 provider（mock/openai），即时生效。api_key 为空则沿用现有 key。"""
        if provider not in ("mock", "openai"):
            raise ModelError(f"unknown provider: {provider}")
        if api_key:
            self._runtime_api_key = api_key
        s = Settings(
            llm_provider=provider,
            llm_model=model or self.settings.llm_model,
            llm_base_url=base_url or self.settings.llm_base_url,
            llm_api_key=self._runtime_api_key or self.settings.llm_api_key,
        )
        self.provider = self._build_provider(s)
        self.default_model = s.llm_model
        self.router.set_default_model(s.llm_model)  # §8 运行时模型同步到路由

    async def complete(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        model: str | None = None,
        latency_ms: int = 0,
        token: CancellationToken | None = None,
        tier: str = "medium",
        tenant_id: str | None = None,
    ) -> ModelResult:
        """统一出口：路由 → 降级链 → 限流 → 熔断 → provider 调用（§8.2/§8.3/§9.3/§9.4）。"""
        models = self.router.fallback_chain(tier=tier, model=model)
        last_exc: ModelError | None = None
        for resolved in models:
            try:
                # 先取默认 provider/health（429/错误统计在任一分支都要用）
                provider = self.provider
                health = self.health
                # §37 LLM 限流：全局 + 租户
                if not await self.limiter.acquire(f"llm:global:{resolved}"):
                    raise ModelRateLimitError("global LLM rate limited", detail={"model": resolved})
                if tenant_id and not await self.limiter.acquire(f"llm:tenant:{tenant_id}:{resolved}"):
                    raise ModelRateLimitError("tenant LLM rate limited", detail={"tenant": tenant_id})

                # §39 熔断
                if not self.breaker.allow():
                    raise ModelError("LLM circuit breaker open", code="MODEL_BREAKER_OPEN")

                # §52 调度：池内按 capability/health/quota/cost/latency 过滤 + 负载均衡
                if self.pool is not None:
                    entry, decision = self.scheduler.pick(self.pool, tier=tier)
                    provider = entry.provider
                    health = entry.health
                    self.last_schedule_reason = "; ".join(decision["passed_filters"])
                    try:
                        trace.get_current_span().set_attribute("scheduler.reason", self.last_schedule_reason)
                    except Exception:  # noqa: BLE001 无当前 span 时忽略
                        pass

                _t0 = time.monotonic()
                result = await provider.complete(messages, tools, resolved, token=token)
                self.breaker.record(True)
                health.record(ok=True, latency_ms=(time.monotonic() - _t0) * 1000)
                return result
            except ModelRateLimitError:
                self.breaker.record(False)
                health.record(ok=False, is_429=True)  # §52.3 429 率驱动 Degraded
                raise  # §8.3 429 交给上层重试，不降级
            except (ModelTimeoutError, ModelError) as exc:
                self.breaker.record(False)
                health.record(ok=False)
                last_exc = exc
                continue  # §8.2/§9.4 降级到下一档模型
        assert last_exc is not None
        raise last_exc

    async def stream_complete(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        model: str | None = None,
        token: CancellationToken | None = None,
        tier: str = "medium",
        tenant_id: str | None = None,
        on_token=None,
    ) -> ModelResult:
        """流式统一出口：同 complete 管线（路由/限流/熔断），provider 走 stream（内容增量回调 on_token）。"""
        models = self.router.fallback_chain(tier=tier, model=model)
        last_exc: ModelError | None = None
        for resolved in models:
            try:
                provider = self.provider
                health = self.health
                if not await self.limiter.acquire(f"llm:global:{resolved}"):
                    raise ModelRateLimitError("global LLM rate limited", detail={"model": resolved})
                if tenant_id and not await self.limiter.acquire(f"llm:tenant:{tenant_id}:{resolved}"):
                    raise ModelRateLimitError("tenant LLM rate limited", detail={"tenant": tenant_id})
                if not self.breaker.allow():
                    raise ModelError("LLM circuit breaker open", code="MODEL_BREAKER_OPEN")
                if self.pool is not None:
                    entry, decision = self.scheduler.pick(self.pool, tier=tier)
                    provider = entry.provider
                    health = entry.health
                _t0 = time.monotonic()
                result = await provider.stream(messages, tools, resolved, on_token=on_token, token=token)
                self.breaker.record(True)
                health.record(ok=True, latency_ms=(time.monotonic() - _t0) * 1000)
                return result
            except ModelRateLimitError:
                self.breaker.record(False)
                health.record(ok=False, is_429=True)
                raise
            except (ModelTimeoutError, ModelError) as exc:
                self.breaker.record(False)
                health.record(ok=False)
                last_exc = exc
                continue
        assert last_exc is not None
        raise last_exc
