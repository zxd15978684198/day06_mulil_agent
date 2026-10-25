"""OpenTelemetry 初始化：Trace / Metrics / 自动插桩 / Langfuse 属性注入。

设计边界（与 `docs/plans/可观测性升级计划.md` 一致）：

* **默认 no-op**：没有配置 OTLP 端点、也没有显式选择 console 时，不创建
  Provider、不启动后台导出线程，业务和测试完全不受影响；
* **进程内只初始化一次**：`trace.set_tracer_provider()` 一个进程只能生效一次；
* **日志不在这里**：日志走 stdout + Grafana Alloy → Loki，不引入 OTel Logs SDK；
* **不采集 Prompt/回答**：由 `OPENINFERENCE_HIDE_INPUTS/OUTPUTS` 控制；
* **Langfuse 密钥只在 Collector**：应用只连 Collector，不持有 Langfuse secret。

注意：本模块会在 import 期之外调用（`agent_api.py` / `main.py` 的启动阶段），
不要在这里读业务数据、不要改数据库、不要改 `RunContext`。
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    MetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanExporter,
)
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_OFF,
    ALWAYS_ON,
    ParentBased,
    Sampler,
    TraceIdRatioBased,
)
from opentelemetry.trace import Span

from personal_assistant import __version__
from personal_assistant.request_context import current_request_context

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# 安全默认值：OpenInference 默认会采集 Prompt / 工具入参 / 模型回答。
# 只有显式设为 false 才开启（仅限本地调试）；`.env.example` 也保持 true。
os.environ.setdefault("OPENINFERENCE_HIDE_INPUTS", "true")
os.environ.setdefault("OPENINFERENCE_HIDE_OUTPUTS", "true")

_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None
_initialized = False


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _resource() -> Resource:
    """所有 Trace/Metrics 共用的资源标签。"""

    return Resource.create(
        {
            "service.name": _env("OTEL_SERVICE_NAME", "employee-agent"),
            "service.version": _env("APP_VERSION", __version__),
            "deployment.environment.name": _env("DEPLOYMENT_ENV", "development"),
        }
    )


def _sampler() -> Sampler:
    """按 OTel 标准变量选择采样器；默认 parentbased_traceidratio=1.0。"""

    name = _env("OTEL_TRACES_SAMPLER", "parentbased_traceidratio").lower()
    if name in {"always_off", "parentbased_always_off"}:
        base: Sampler = ALWAYS_OFF
    elif name in {"traceidratio", "parentbased_traceidratio"}:
        try:
            ratio = float(_env("OTEL_TRACES_SAMPLER_ARG", "1.0"))
        except ValueError:
            ratio = 1.0
        base = TraceIdRatioBased(min(max(ratio, 0.0), 1.0))
    else:
        base = ALWAYS_ON

    if name.startswith("parentbased_"):
        return ParentBased(base)
    return base


def _trace_exporter() -> SpanExporter | None:
    """otlp / console / none 三态；otlp 没端点时视为未配置。"""

    kind = _env("OTEL_TRACES_EXPORTER", "otlp").lower()
    if kind in {"", "none", "false", "0"}:
        return None
    if kind == "console":
        return ConsoleSpanExporter()

    endpoint = _env("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or _env(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    if not endpoint:
        return None
    # 不传参数：让 exporter 读取标准 OTEL_EXPORTER_OTLP_*（headers/timeout/protocol），
    # 通用 endpoint 会自动补 /v1/traces。
    return OTLPSpanExporter()


def _metric_exporter() -> MetricExporter | None:
    kind = _env("OTEL_METRICS_EXPORTER", "otlp").lower()
    if kind in {"", "none", "false", "0"}:
        return None
    if kind == "console":
        return ConsoleMetricExporter()

    endpoint = _env("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT") or _env(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    if not endpoint:
        return None
    return OTLPMetricExporter()


def _metric_interval_millis() -> int:
    try:
        return max(1000, int(_env("OTEL_METRIC_EXPORT_INTERVAL", "5000")))
    except ValueError:
        return 5000


class _LangfuseAttributeProcessor(SpanProcessor):
    """把请求上下文里的业务 ID 复制到每个 Span。

    Langfuse 的筛选/聚合是跨 observation 的，`langfuse.session.id` 和
    `langfuse.user.id` 只放根 Span 会在子 Span 上查不到；这里统一注入。
    没有绑定请求上下文时（例如索引构建、CLI 启动）什么都不做。
    """

    def on_start(self, span: Span, parent_context: Any = None) -> None:
        ctx = current_request_context()
        if ctx is None or not span.is_recording():
            return
        span.set_attribute("langfuse.session.id", ctx.thread_id)
        span.set_attribute("langfuse.user.id", ctx.user_id_hash)
        span.set_attribute("langfuse.trace.name", "employee-agent.turn")
        span.set_attribute("langfuse.trace.tags", ["employee-agent", ctx.role])
        span.set_attribute("langfuse.trace.metadata.request_id", ctx.request_id)
        span.set_attribute("langfuse.trace.metadata.run_id", ctx.run_id)

    def on_end(self, span: ReadableSpan) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True


def _instrument_libraries(provider: TracerProvider, engine: Engine | None) -> None:
    """自动插桩；单条失败只告警，不能让业务启动失败。"""

    try:
        from opentelemetry.instrumentation.httpx import (
            HTTPXClientInstrumentor,
        )

        HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    except Exception:  # noqa: BLE001 —— 观测失败不影响业务
        logger.warning("HTTPX 自动插桩失败，继续启动", exc_info=True)

    if engine is not None:
        try:
            from opentelemetry.instrumentation.sqlalchemy import (
                SQLAlchemyInstrumentor,
            )

            SQLAlchemyInstrumentor().instrument(engine=engine, tracer_provider=provider)
        except Exception:  # noqa: BLE001
            logger.warning("SQLAlchemy 自动插桩失败，继续启动", exc_info=True)

    try:
        from openinference.instrumentation.langchain import (
            LangChainInstrumentor,
        )

        LangChainInstrumentor().instrument(tracer_provider=provider)
    except Exception:  # noqa: BLE001
        logger.warning(
            "LangChain 自动插桩失败，继续启动（业务不受影响）",
            exc_info=True,
        )


def setup_telemetry(*, engine: Engine | None = None) -> bool:
    """初始化 Trace/Metrics 并挂自动插桩；返回是否真正启用。

    幂等：同一进程重复调用只生效第一次。
    """

    global _initialized, _provider, _meter_provider
    if _initialized:
        return _provider is not None
    _initialized = True

    if _flag("OTEL_SDK_DISABLED"):
        logger.info("OpenTelemetry 已通过 OTEL_SDK_DISABLED 关闭")
        return False

    trace_exporter = _trace_exporter()
    metric_exporter = _metric_exporter()
    if trace_exporter is None and metric_exporter is None:
        logger.info("OpenTelemetry 未启用：未配置 OTLP 端点，也未选择 console exporter")
        return False

    resource = _resource()

    if trace_exporter is not None:
        provider = TracerProvider(resource=resource, sampler=_sampler())
        provider.add_span_processor(_LangfuseAttributeProcessor())
        provider.add_span_processor(
            BatchSpanProcessor(trace_exporter, schedule_delay_millis=2000)
        )
        trace.set_tracer_provider(provider)
        _provider = provider
        _instrument_libraries(provider, engine)

    if metric_exporter is not None:
        meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[
                PeriodicExportingMetricReader(
                    metric_exporter,
                    export_interval_millis=_metric_interval_millis(),
                )
            ],
        )
        metrics.set_meter_provider(meter_provider)
        _meter_provider = meter_provider

    logger.info(
        "OpenTelemetry 已启用：service=%s traces=%s metrics=%s",
        _env("OTEL_SERVICE_NAME", "employee-agent"),
        _env("OTEL_TRACES_EXPORTER", "otlp"),
        _env("OTEL_METRICS_EXPORTER", "otlp"),
    )
    return True


def instrument_fastapi(app: FastAPI) -> None:
    """给已创建、已加完业务中间件的 FastAPI app 挂 ASGI 中间件。

    必须在 `app.add_middleware(CORSMiddleware, ...)` 之后调用，保证 OTel
    在 CORS 外层；不要放进 lifespan（middleware 栈已经构建完）。
    """

    if _provider is None:
        return
    try:
        from opentelemetry.instrumentation.fastapi import (
            FastAPIInstrumentor,
        )

        excluded = _env("OTEL_PYTHON_FASTAPI_EXCLUDED_URLS") or None
        FastAPIInstrumentor.instrument_app(
            app, tracer_provider=_provider, excluded_urls=excluded
        )
    except Exception:  # noqa: BLE001
        logger.warning("FastAPI 自动插桩失败，继续启动", exc_info=True)


def annotate_current_span(
    *,
    thread_id: str,
    role: str,
    user_id_hash: str,
) -> None:
    """把 Langfuse 顶层属性补到当前 Span（通常是 FastAPI 的 HTTP 根 Span）。

    `agent.turn` 和子 Span 由 `_LangfuseAttributeProcessor` 注入；HTTP Span 在
    请求上下文绑定之前就创建了，需要路由入口显式补一次，否则 Langfuse 按
    `session.id` 过滤时看不到根 Span。
    """

    span = trace.get_current_span()
    if not span.is_recording():
        return
    span.set_attribute("langfuse.session.id", thread_id)
    span.set_attribute("langfuse.user.id", user_id_hash)
    span.set_attribute("langfuse.trace.name", "employee-agent.turn")
    span.set_attribute("langfuse.trace.tags", ["employee-agent", role])


def current_trace_ids() -> tuple[str | None, str | None]:
    """返回当前 Span 的 (trace_id, span_id)；没有有效上下文时返回 (None, None)。"""

    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None, None
    return (
        f"{span_context.trace_id:032x}",
        f"{span_context.span_id:016x}",
    )


def shutdown_telemetry() -> None:
    """flush 并关闭 Provider；可重复调用。

    BatchSpanProcessor / PeriodicExportingMetricReader 都有缓冲，进程退出前
    不 flush 会丢最后一批数据。
    """

    global _provider, _meter_provider

    if _meter_provider is not None:
        try:
            _meter_provider.force_flush()
        finally:
            _meter_provider.shutdown()
            _meter_provider = None

    if _provider is not None:
        try:
            _provider.force_flush()
        finally:
            _provider.shutdown()
            _provider = None
