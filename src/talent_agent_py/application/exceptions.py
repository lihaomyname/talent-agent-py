"""应用层统一异常，供 API 映射为稳定错误响应。"""


class TalentAgentError(Exception):
    """人才 Agent 可预期异常的基类。"""

    code = "TALENT_AGENT_ERROR"


class SessionNotFoundError(TalentAgentError):
    """会话不存在，或当前用户无权访问该会话。"""

    code = "SESSION_NOT_FOUND"


class RunNotFoundError(TalentAgentError):
    """指定的运行记录不存在。"""

    code = "RUN_NOT_FOUND"


class InvalidClarificationAnswerError(TalentAgentError):
    """澄清问题已过期，或答案不在允许选项中。"""

    code = "INVALID_CLARIFICATION_ANSWER"


class StalePageReferenceError(TalentAgentError):
    """分页引用不属于当前 SearchPlan。"""

    code = "STALE_PAGE_REFERENCE"


class ModelOutputError(TalentAgentError):
    """大模型未能返回符合结构化协议的内容。"""

    code = "MODEL_ERROR"


class TalentSearchDeniedError(TalentAgentError):
    """Java 权威服务拒绝当前用户的人才搜索权限。"""

    code = "DENIED"


class TalentSearchDependencyError(TalentAgentError):
    """Java、ES 或网络依赖异常。"""

    code = "DEPENDENCY_ERROR"


class RunSupersededError(TalentAgentError):
    """当前运行已被更新的用户消息替代。"""

    code = "SUPERSEDED"


class FeatureDisabledError(TalentAgentError):
    """当前环境尚未开启自然语言找人入口。"""

    code = "FEATURE_DISABLED"
