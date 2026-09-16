"""应用异常到 HTTP 错误的统一映射。"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from talent_agent_py.application.exceptions import (
    FeatureDisabledError,
    InvalidClarificationAnswerError,
    ModelOutputError,
    RunNotFoundError,
    SessionNotFoundError,
    StalePageReferenceError,
    TalentAgentError,
    TalentSearchDeniedError,
    TalentSearchDependencyError,
)


def register_error_handlers(app: FastAPI) -> None:
    """注册稳定错误码，避免向客户端暴露内部堆栈。"""

    @app.exception_handler(SessionNotFoundError)
    @app.exception_handler(RunNotFoundError)
    async def not_found_handler(request: Request, exc: TalentAgentError) -> JSONResponse:
        """返回 404 及稳定错误码，表示会话或运行不可访问。"""

        return JSONResponse(status_code=404, content={"code": exc.code, "message": str(exc)})

    @app.exception_handler(InvalidClarificationAnswerError)
    @app.exception_handler(StalePageReferenceError)
    async def conflict_handler(request: Request, exc: TalentAgentError) -> JSONResponse:
        """返回 409，提示澄清答案或分页引用与当前状态不匹配。"""

        return JSONResponse(status_code=409, content={"code": exc.code, "message": str(exc)})

    @app.exception_handler(TalentAgentError)
    async def business_error_handler(request: Request, exc: TalentAgentError) -> JSONResponse:
        """将未单独分类的应用异常转换为 502 业务错误响应。"""

        return JSONResponse(status_code=502, content={"code": exc.code, "message": str(exc)})

    @app.exception_handler(FeatureDisabledError)
    async def feature_disabled_handler(request: Request, exc: TalentAgentError) -> JSONResponse:
        """返回 503，说明当前配置未启用 Agent。"""

        return JSONResponse(status_code=503, content={"code": exc.code, "message": str(exc)})

    @app.exception_handler(TalentSearchDeniedError)
    async def denied_handler(request: Request, exc: TalentAgentError) -> JSONResponse:
        """返回 403，说明招聘接口拒绝当前用户访问。"""

        return JSONResponse(status_code=403, content={"code": exc.code, "message": str(exc)})

    @app.exception_handler(ModelOutputError)
    @app.exception_handler(TalentSearchDependencyError)
    async def upstream_handler(request: Request, exc: TalentAgentError) -> JSONResponse:
        """返回 502，说明模型或招聘依赖未能完成本次调用。"""

        return JSONResponse(status_code=502, content={"code": exc.code, "message": str(exc)})
