"""业务异常到 HTTP 状态码和稳定错误码的映射测试。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from talent_agent_py.api.errors import register_error_handlers
from talent_agent_py.application.exceptions import (
    FeatureDisabledError,
    InvalidClarificationAnswerError,
    ModelOutputError,
    SessionNotFoundError,
    TalentSearchDeniedError,
    TalentSearchDependencyError,
)


def test_business_errors_have_distinct_http_mappings():
    app = FastAPI()
    register_error_handlers(app)
    cases = {
        "missing": (SessionNotFoundError("不存在"), 404, "SESSION_NOT_FOUND"),
        "clarification": (
            InvalidClarificationAnswerError("答案无效"),
            409,
            "INVALID_CLARIFICATION_ANSWER",
        ),
        "disabled": (FeatureDisabledError("未开启"), 503, "FEATURE_DISABLED"),
        "denied": (TalentSearchDeniedError("拒绝"), 403, "DENIED"),
        "model": (ModelOutputError("模型错误"), 502, "MODEL_ERROR"),
        "dependency": (
            TalentSearchDependencyError("依赖错误"),
            502,
            "DEPENDENCY_ERROR",
        ),
    }

    for path, (error, expected_status, expected_code) in cases.items():
        async def fail(current_error=error):
            raise current_error

        app.add_api_route(f"/{path}", fail)

    with TestClient(app, raise_server_exceptions=False) as client:
        for path, (_, expected_status, expected_code) in cases.items():
            response = client.get(f"/{path}")
            assert response.status_code == expected_status
            assert response.json()["code"] == expected_code
