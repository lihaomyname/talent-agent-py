"""消息路由测试。"""

from talent_agent_py.application.message_router import MessageRouter
from talent_agent_py.domain.enums import MessageType
from tests.fakes import FakeLLMClient


async def test_casual_message_does_not_call_llm_or_interrupt():
    llm = FakeLLMClient()
    route = await MessageRouter(llm).route(
        message="哈哈哈",
        current_plan=None,
        has_pending_clarification=False,
    )
    assert route.message_type is MessageType.CASUAL_CHAT
    assert route.affects_active_run is False
    assert llm.classify_calls == 0


async def test_unknown_free_text_uses_structured_classifier():
    llm = FakeLLMClient()
    route = await MessageRouter(llm).route(
        message="帮我找Java开发",
        current_plan=None,
        has_pending_clarification=False,
    )
    assert route.message_type is MessageType.SEARCH_NEW
    assert llm.classify_calls == 1
