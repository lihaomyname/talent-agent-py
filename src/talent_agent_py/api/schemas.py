"""HTTP 请求模型。"""

from pydantic import Field

from talent_agent_py.domain.base import StrictModel
from talent_agent_py.domain.conversation import ClarificationAnswer, PageReference


class SendMessageRequest(StrictModel):
    """发送普通文本或结构化澄清答案。"""

    # 前端生成的幂等消息标识；重试应复用同一个值。
    client_message_id: str = Field(min_length=1, max_length=128)
    # 用户自然语言消息或澄清选项的展示文本。
    content: str = Field(min_length=1, max_length=4000)
    # 结构化卡片答案；普通输入时为空。
    clarification_answer: ClarificationAnswer | None = None


class PageRequest(StrictModel):
    """不经过 LLM 的分页请求。"""

    # 服务端返回的分页引用，包含会话、计划版本和目标页。
    reference: PageReference
