"""结构化日志和基础 HTTP 指标。"""

import time

import structlog
from fastapi import FastAPI, Request
from prometheus_client import Counter, Histogram, make_asgi_app

REQUESTS = Counter(
    "talent_agent_http_requests_total",
    "HTTP 请求总数",
    ["method", "path", "status"],
)
LATENCY = Histogram(
    "talent_agent_http_request_seconds",
    "HTTP 请求耗时",
    ["method", "path"],
)
RUN_OUTCOMES = Counter(
    "talent_agent_run_outcomes_total",
    "Agent Run 结果数",
    ["status"],
)
EXTERNAL_CALLS = Counter(
    "talent_agent_external_calls_total",
    "模型和 Java 外部调用数",
    ["dependency", "operation"],
)
CLARIFICATIONS = Counter(
    "talent_agent_clarifications_total",
    "澄清卡生成数",
    ["kind"],
)
RUN_STAGES = Counter(
    "talent_agent_run_stages_total",
    "各运行阶段进入次数",
    ["stage"],
)
PARSE_OUTCOMES = Counter(
    "talent_agent_parse_outcomes_total",
    "结构化语义解析结果数",
    ["operation", "outcome"],
)
JAVA_LATENCY = Histogram(
    "talent_agent_java_call_seconds",
    "Java 实体解析和人才搜索耗时",
    ["operation"],
)
INTERRUPTIONS = Counter(
    "talent_agent_interruptions_total",
    "运行被替代或显式取消的次数",
    ["kind"],
)


def configure_telemetry(app: FastAPI) -> None:
    """配置 JSON 日志、请求指标和 Prometheus 端点。"""

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ]
    )

    @app.middleware("http")
    async def record_http_metrics(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        path = request.url.path
        REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        LATENCY.labels(request.method, path).observe(time.perf_counter() - started)
        return response

    app.mount("/metrics", make_asgi_app())
