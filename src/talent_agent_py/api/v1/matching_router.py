"""需求草稿和匹配运行接口，复用现有会话身份。"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from talent_agent_py.api.dependencies import get_user_context
from talent_agent_py.domain.conversation import UserContext
from talent_agent_py.domain.matching import SearchRequirements
from talent_agent_py.infrastructure.clients.matching_llm import validate_image

router = APIRouter()
UserDep = Annotated[UserContext, Depends(get_user_context)]


class ActionRequest(BaseModel):
    request_key: str = Field(min_length=1, max_length=64)


class RequirementRequest(ActionRequest):
    content: str = Field(min_length=1, max_length=20000)


class ConfirmRequest(ActionRequest):
    requirements: SearchRequirements


@router.get("/features")
async def features(request: Request):
    settings = request.app.state.settings
    return {"matching": settings.enable_matching,
            "images": settings.enable_matching and bool(settings.vision_base_url and settings.vision_api_key)}


@router.post("/sessions/{session_id}/requirements")
async def prepare(session_id: str, payload: RequirementRequest, user: UserDep, request: Request):
    return await request.app.state.matching_service.prepare(
        session_id, user, payload.content, payload.request_key,
    )


@router.post("/sessions/{session_id}/requirement-images")
async def prepare_image(
    session_id: str, user: UserDep, request: Request,
    image: Annotated[UploadFile, File()],
    request_key: Annotated[str, Form(min_length=1, max_length=64)],
    content: Annotated[str, Form(max_length=20000)] = "",
):
    service = request.app.state.matching_service
    service.require_enabled()
    await request.app.state.session_service.get(session_id, user)
    try:
        data = await image.read(service.settings.image_max_bytes + 1)
        mime = validate_image(data, service.settings)
        if image.content_type != mime:
            raise HTTPException(status_code=400, detail="图片内容与声明格式不一致")
        natural_language = await service.extract_image_requirement(content, data)
        return await request.app.state.agent_service.handle_message(
            session_id=session_id,
            client_message_id=request_key,
            content=natural_language,
            user=user,
        )
    finally:
        await image.close()


@router.post("/sessions/{session_id}/requirements/{requirement_id}/confirm")
async def confirm(
    session_id: str, requirement_id: str, payload: ConfirmRequest, user: UserDep, request: Request,
):
    return await request.app.state.matching_service.confirm(
        session_id, user, requirement_id, payload.request_key, payload.requirements,
    )


@router.get("/sessions/{session_id}/matches/{run_id}")
async def get_match(
    session_id: str, run_id: str, user: UserDep, request: Request, include_results: bool = False,
):
    return await request.app.state.matching_service.get(session_id, run_id, user, include_results)


@router.post("/sessions/{session_id}/matches/{run_id}/continue")
async def continue_match(
    session_id: str, run_id: str, payload: ActionRequest, user: UserDep, request: Request,
):
    return await request.app.state.matching_service.continue_run(session_id, run_id, user, payload.request_key)


@router.post("/sessions/{session_id}/matches/{run_id}/cancel")
async def cancel_match(session_id: str, run_id: str, user: UserDep, request: Request):
    session = await request.app.state.session_service.get(session_id, user)
    if session.active_run_id != run_id:
        raise HTTPException(status_code=409, detail="这不是当前运行")
    return await request.app.state.agent_service.cancel_current(session_id, user)
