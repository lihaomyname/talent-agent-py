"""结构化日志、业务载荷脱敏和基础 HTTP 指标。"""

import json
import time
from typing import Any

import structlog
from fastapi import FastAPI, Request
from prometheus_client import Counter, Histogram, make_asgi_app
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_SECRET_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "authopenidtoken",
    "api_key",
    "apikey",
    "token",
    "password",
}
_PII_KEYS = {
    "resumebaseappemail",
    "resumebaseappmobile",
    "wechat",
    "mobile",
    "phone",
    "telephone",
    "email",
    "idnumber",
    "id_card",
    "identitynumber",
}
_MAX_LOG_BODY_BYTES = 64 * 1024

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


def sanitize_log_value(value: Any, *, key: str = "") -> Any:
    """递归保留业务明文，同时屏蔽认证凭据和候选人敏感信息。"""

    normalized_key = key.lower().replace("-", "").replace("_", "")
    if normalized_key in {item.replace("_", "").replace("-", "") for item in _SECRET_KEYS | _PII_KEYS}:
        return "***已脱敏***"
    if isinstance(value, dict):
        return {
            str(child_key): sanitize_log_value(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_log_value(item) for item in value]
    if hasattr(value, "model_dump"):
        return sanitize_log_value(value.model_dump(mode="json"))
    return value


def decode_log_body(body: bytes) -> Any:
    """把 JSON 请求体还原为可读对象，非 JSON 内容按 UTF-8 文本记录。"""

    if not body:
        return None
    clipped = body[:_MAX_LOG_BODY_BYTES]
    try:
        value = json.loads(clipped)
    except (json.JSONDecodeError, UnicodeDecodeError):
        value = clipped.decode("utf-8", errors="replace")
    if len(body) > _MAX_LOG_BODY_BYTES:
        return {"content": sanitize_log_value(value), "truncated": True}
    return sanitize_log_value(value)


class RequestResponseLogMiddleware:
    """在 ASGI 边界记录每次 HTTP 请求和响应，不改变流式传输行为。"""

    def __init__(self, app: ASGIApp) -> None:
        """保存下游 ASGI 应用和 HTTP 日志器。"""

        # 下游 ASGI 应用，接收原样透传的请求消息。
        self.app = app
        # HTTP 请求响应专用的结构化日志器。
        self.logger = structlog.get_logger("talent_agent_py.http")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """透传 ASGI 消息并采集请求响应日志，不改变消息发送顺序。"""

        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_body = bytearray()
        response_body = bytearray()
        status_code = 500
        # 匹配和图片端点仅记录请求元数据，不采集图片、需求或候选人正文。
        metadata_only = any(part in scope.get("path", "") for part in (
            "/requirements", "/requirement-images", "/matches",
        ))

        async def logged_receive() -> Message:
            """接收并暂存请求体片段，原样返回下游需要的 ASGI 消息。"""

            message = await receive()
            if not metadata_only and message["type"] == "http.request" and len(request_body) < _MAX_LOG_BODY_BYTES:
                request_body.extend(message.get("body", b""))
            return message

        async def logged_send(message: Message) -> None:
            """采集响应状态及正文片段，再将消息原样发送给服务器。"""

            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            elif not metadata_only and message["type"] == "http.response.body" and len(response_body) < _MAX_LOG_BODY_BYTES:
                response_body.extend(message.get("body", b""))
            await send(message)

        started = time.perf_counter()
        try:
            await self.app(scope, logged_receive, logged_send)
        finally:
            headers = {
                key.decode("latin-1"): value.decode("latin-1")
                for key, value in scope.get("headers", [])
            }
            self.logger.info(
                "HTTP 请求响应",
                method=scope.get("method"),
                path=scope.get("path"),
                query_string=scope.get("query_string", b"").decode("utf-8", errors="replace"),
                request_headers=sanitize_log_value(headers),
                request_body=decode_log_body(bytes(request_body)),
                status_code=status_code,
                response_body=decode_log_body(bytes(response_body)),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
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
    async def record_http_metrics(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """执行下一层中间件，记录耗时和计数，并返回原响应。"""

        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        LATENCY.labels(request.method, path).observe(time.perf_counter() - started)
        return response

    app.mount("/metrics", make_asgi_app())
