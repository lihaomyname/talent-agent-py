"""截图入口：先转为自然语言，再复用原消息流程。"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from talent_agent_py.api.dependencies import get_user_context
from talent_agent_py.domain.conversation import UserContext
from talent_agent_py.infrastructure.clients.matching_llm import validate_image

router = APIRouter()
UserDep = Annotated[UserContext, Depends(get_user_context)]


@router.get("/features")
async def features(request: Request):
    settings = request.app.state.settings
    return {
        "matching": settings.enable_matching,
        "images": settings.enable_matching
        and bool(settings.vision_base_url and settings.vision_api_key),
    }


@router.post("/sessions/{session_id}/requirement-images")
async def prepare_image(
    session_id: str,
    user: UserDep,
    request: Request,
    image: Annotated[UploadFile, File()],
    request_key: Annotated[str, Form(min_length=1, max_length=64)],
    content: Annotated[str, Form(max_length=20000)] = "",
):
    settings = request.app.state.settings
    if not settings.enable_matching:
        raise HTTPException(status_code=404, detail="截图识别未启用")
    await request.app.state.session_service.get(session_id, user)
    try:
        data = await image.read(settings.image_max_bytes + 1)
        mime = validate_image(data, settings)
        if image.content_type != mime:
            raise HTTPException(status_code=400, detail="图片内容与声明格式不一致")
        natural_language = await request.app.state.image_llm.extract_image_text(content, data)
        return await request.app.state.agent_service.handle_message(
            session_id=session_id,
            client_message_id=request_key,
            content=natural_language,
            user=user,
        )
    finally:
        await image.close()
