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
    async def not_found_handler(request: Request, exc: TalentAgentError):
        return JSONResponse(status_code=404, content={"code": exc.code, "message": str(exc)})

    @app.exception_handler(InvalidClarificationAnswerError)
    @app.exception_handler(StalePageReferenceError)
    async def conflict_handler(request: Request, exc: TalentAgentError):
        return JSONResponse(status_code=409, content={"code": exc.code, "message": str(exc)})

    @app.exception_handler(TalentAgentError)
    async def business_error_handler(request: Request, exc: TalentAgentError):
        return JSONResponse(status_code=502, content={"code": exc.code, "message": str(exc)})

    @app.exception_handler(FeatureDisabledError)
    async def feature_disabled_handler(request: Request, exc: TalentAgentError):
        return JSONResponse(status_code=503, content={"code": exc.code, "message": str(exc)})

    @app.exception_handler(TalentSearchDeniedError)
    async def denied_handler(request: Request, exc: TalentAgentError):
        return JSONResponse(status_code=403, content={"code": exc.code, "message": str(exc)})

    @app.exception_handler(ModelOutputError)
    @app.exception_handler(TalentSearchDependencyError)
    async def upstream_handler(request: Request, exc: TalentAgentError):
        return JSONResponse(status_code=502, content={"code": exc.code, "message": str(exc)})
