"""规则优先的消息入口路由。"""

from talent_agent_py.application.ports.llm import LLMClient
from talent_agent_py.domain.conversation import MessageRoute
from talent_agent_py.domain.enums import MessageType
from talent_agent_py.domain.plan import SearchPlan


class MessageRouter:
    """先处理确定性消息，无法判断时才调用轻量分类模型。"""

    _CASUAL = {"你好", "您好", "哈哈", "哈哈哈", "谢谢", "好的", "收到", "ok", "OK"}
    _STOP = {"停止", "停止搜索", "取消", "取消搜索", "不用找了", "别找了"}
    _STATUS = {"进度", "进度怎么样", "找到哪一步了", "还要多久", "搜索怎么样了"}
    _PAGE = {"下一页", "再看一些", "更多", "上一页"}
    _NEW_MARKERS = ("重新找", "重新搜索", "换一批人", "清空条件", "从头开始")
    _PATCH_MARKERS = ("改成", "换成", "只看", "加上", "增加", "去掉", "删除", "不要")

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def route(
        self,
        *,
        message: str,
        current_plan: SearchPlan | None,
        has_pending_clarification: bool,
        structured_clarification: bool = False,
        structured_page_action: bool = False,
    ) -> MessageRoute:
        """返回消息类型，并明确它是否应该替代当前搜索 Run。"""

        text = message.strip()
        if structured_clarification:
            return MessageRoute(
                message_type=MessageType.CLARIFICATION_ANSWER,
                affects_active_run=True,
                confidence=1.0,
                reason_code="STRUCTURED_CLARIFICATION",
            )
        if structured_page_action:
            return MessageRoute(
                message_type=MessageType.PAGE_ACTION,
                affects_active_run=False,
                confidence=1.0,
                reason_code="STRUCTURED_PAGE_ACTION",
            )
        if text in self._CASUAL:
            return MessageRoute(
                message_type=MessageType.CASUAL_CHAT,
                affects_active_run=False,
                confidence=1.0,
                reason_code="CASUAL_RULE",
            )
        if text in self._STOP:
            return MessageRoute(
                message_type=MessageType.CONTROL_STOP,
                affects_active_run=True,
                confidence=1.0,
                reason_code="STOP_RULE",
            )
        if text in self._STATUS:
            return MessageRoute(
                message_type=MessageType.STATUS_QUERY,
                affects_active_run=False,
                confidence=1.0,
                reason_code="STATUS_RULE",
            )
        if text in self._PAGE:
            return MessageRoute(
                message_type=MessageType.PAGE_ACTION,
                affects_active_run=False,
                confidence=1.0,
                reason_code="PAGE_RULE",
                page_delta=-1 if text == "上一页" else 1,
            )
        if any(marker in text for marker in self._NEW_MARKERS):
            return MessageRoute(
                message_type=MessageType.SEARCH_NEW,
                affects_active_run=True,
                confidence=0.95,
                reason_code="NEW_SEARCH_RULE",
            )
        if current_plan and any(marker in text for marker in self._PATCH_MARKERS):
            return MessageRoute(
                message_type=MessageType.SEARCH_PATCH,
                affects_active_run=True,
                confidence=0.9,
                reason_code="PATCH_RULE",
            )

        return await self._llm.classify_message(
            message=text,
            current_plan=current_plan,
            has_pending_clarification=has_pending_clarification,
        )
