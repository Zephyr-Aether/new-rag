"""OpenTelemetry 封装（§7）。

默认无 OTLP 端点 => 不导出，trace 以结构化日志/console 呈现；
生产配 APP_OTLP_ENDPOINT 后导出到 Collector。
所有 span 必须带 §7.3 全量属性，由本模块强制约定。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.settings import Settings


def setup_otel(settings: Settings) -> None:
    """初始化 tracer provider；无端点时用 no-op（等价不导出）。"""
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: settings.service_name}))
    if settings.otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint)))
    trace.set_tracer_provider(provider)


def get_tracer() -> trace.Tracer:
    return trace.get_tracer(__name__)


@asynccontextmanager
async def run_span(name: str, **attributes) -> AsyncIterator[None]:
    """便捷 span 包装：进入即开 span 并附属性，退出即结束。"""
    with get_tracer().start_as_current_span(name) as span:
        if attributes:
            span.set_attributes(attributes)
        yield


@asynccontextmanager
async def span(name: str, **attributes) -> AsyncIterator[Any]:
    """span 包装，yield 出 span 对象供事后补属性（如 tokens/cost）。"""
    with get_tracer().start_as_current_span(name) as sp:
        if attributes:
            sp.set_attributes(attributes)
        yield sp
