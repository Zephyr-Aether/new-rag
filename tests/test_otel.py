"""OTel span 打点（§17）：agent.run / llm.call / tool.execute 必带 run_id 等属性。"""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.agent.runtime.budget import ExecutionBudget
from app.agent.runtime.runtime import execute_run
from app.common.contracts import RunInput


async def test_run_emits_spans(deps):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # set_tracer_provider 对"已设置过"的 provider 会忽略覆盖（OTel 限制），这里强制替换全局
    trace._TRACER_PROVIDER = provider  # noqa: SLF001

    try:
        req = RunInput(tenant_id="t", user_id="u", agent_id="a", session_id="s", text="12 + 30")
        result = await execute_run(
            req, deps, run_id="r-otel", agent_version=1, system_prompt="", budget=ExecutionBudget(max_steps=5)
        )
        assert result.state == "COMPLETED"

        spans = exporter.get_finished_spans()
        exporter.shutdown()
        names = {s.name for s in spans}
        assert "agent.run" in names
        assert "llm.call" in names
        assert "tool.execute" in names

        run_span = next(s for s in spans if s.name == "agent.run")
        assert run_span.attributes.get("run_id") == "r-otel"
        assert run_span.attributes.get("tenant_id") == "t"

        llm_spans = [s for s in spans if s.name == "llm.call"]
        assert any("tokens_in" in (s.attributes or {}) for s in llm_spans)
        tool_span = next(s for s in spans if s.name == "tool.execute")
        assert tool_span.attributes.get("tool_ref") == "calc.add"
    finally:
        trace._TRACER_PROVIDER = TracerProvider()  # noqa: SLF001 复位，避免影响其他测试
