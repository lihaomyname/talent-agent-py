"""HTTP 请求模型。"""

from pydantic import Field

from talent_agent_py.domain.base import StrictModel
from talent_agent_py.domain.conversation import ClarificationAnswer, PageReference


class SendMessageRequest(StrictModel):
    """发送普通文本或结构化澄清答案。"""

    client_message_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=4000)
    clarification_answer: ClarificationAnswer | None = None


class PageRequest(StrictModel):
    """不经过 LLM 的分页请求。"""

    reference: PageReference
