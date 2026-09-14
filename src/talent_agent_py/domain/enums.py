"""模型、持久化和 API 契约共用的稳定领域枚举。"""

from enum import StrEnum


class MessageType(StrEnum):
    """一条新会话消息的业务含义。"""

    CASUAL_CHAT = "CASUAL_CHAT"  # 普通闲聊，不修改也不停止搜索。
    STATUS_QUERY = "STATUS_QUERY"  # 查询当前 Run 的执行进度。
    CONTROL_STOP = "CONTROL_STOP"  # 明确要求停止当前 Run。
    PAGE_ACTION = "PAGE_ACTION"  # 确定性的结果翻页动作。
    CLARIFICATION_ANSWER = "CLARIFICATION_ANSWER"  # 对待处理澄清卡的回答。
    SEARCH_NEW = "SEARCH_NEW"  # 明确发起一份新的搜索计划。
    SEARCH_PATCH = "SEARCH_PATCH"  # 修改当前搜索计划。
    UNKNOWN = "UNKNOWN"  # 意图不够明确，不能安全修改计划。


class RunStatus(StrEnum):
    """一次图执行的生命周期。"""

    QUEUED = "QUEUED"  # 已接收但尚未开始执行。
    RUNNING = "RUNNING"  # 正在执行图节点。
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"  # 等待用户做出选择。
    SUCCEEDED = "SUCCEEDED"  # 已完成，结果可以是 OK 或 EMPTY。
    FAILED = "FAILED"  # 因模型、校验或依赖异常而失败。
    CANCELLED = "CANCELLED"  # 被用户明确停止。
    SUPERSEDED = "SUPERSEDED"  # 被更新的搜索消息替代。


class ResultStatus(StrEnum):
    """一次运行面向用户的结果状态。"""

    OK = "OK"  # 搜索返回至少一名候选人。
    EMPTY = "EMPTY"  # 搜索正常完成，但没有候选人。
    UNSUPPORTED = "UNSUPPORTED"  # 硬条件超出 V1 支持范围。
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"  # 存在阻塞执行的待选项。
    DENIED = "DENIED"  # Java 拒绝当前有效用户的权限。
    MODEL_ERROR = "MODEL_ERROR"  # 自然语言结构化解析失败。
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"  # Java、ES 或其他依赖异常。
    CANCELLED = "CANCELLED"  # 用户明确停止本轮运行。
    SUPERSEDED = "SUPERSEDED"  # 本轮被更新消息替代。


class ExperienceScope(StrEnum):
    """职位和公司的简历经历范围。"""

    CURRENT = "CURRENT"  # 只匹配候选人当前经历。
    CURRENT_OR_HISTORY = "CURRENT_OR_HISTORY"  # 匹配当前或历史经历。


class LocationScope(StrEnum):
    """招聘人员提到的城市语义。"""

    CURRENT_CITY = "CURRENT_CITY"  # 候选人当前居住地。
    EXPECTED_CITY = "EXPECTED_CITY"  # 候选人期望工作地。
    UNKNOWN = "UNKNOWN"  # 城市范围不明确，需要澄清。


class NameMatchMode(StrEnum):
    """候选人姓名的匹配方式。"""

    EXACT = "EXACT"  # 精确匹配候选人姓名。
    FUZZY = "FUZZY"  # 使用 Java 已支持的模糊匹配。


class SupportedField(StrEnum):
    """V1 能够编译为 Java 搜索的九类条件。"""

    APPLICANT_NAME = "applicant_name"  # 候选人姓名。
    CANDIDATE_POSITION = "candidate_position"  # 当前或历史职位名称。
    MINIMUM_DEGREE = "minimum_degree"  # 已完成的最低学历。
    WORK_YEARS = "work_years"  # 总工作年限范围。
    COMPANY = "company"  # 当前或历史任职公司。
    SCHOOL = "school"  # 毕业院校。
    EXPECTED_CITY = "expected_city"  # 期望工作地。
    CURRENT_CITY = "current_city"  # 当前居住地。
    SCHOOL_LEVEL = "school_level"  # 985、211、QS100 等院校等级标签。


class PatchOperation(StrEnum):
    """SearchPlan 允许的修改操作。"""

    ADD = "ADD"  # 增加值或此前不存在的条件。
    REPLACE = "REPLACE"  # 完整替换一个条件。
    REMOVE = "REMOVE"  # 删除一个条件。
    RESET = "RESET"  # 在应用后续操作前清空全部条件。


class ClarificationKind(StrEnum):
    """用于选择安全澄清模板的原因码。"""

    LOCATION_SCOPE = "LOCATION_SCOPE"  # 现居住地与期望工作地之间的选择。
    POSITION_SCOPE = "POSITION_SCOPE"  # 当前职位与当前或历史职位之间的选择。
    COMPANY_SCOPE = "COMPANY_SCOPE"  # 当前公司与当前或历史公司之间的选择。
    ENTITY_AMBIGUITY = "ENTITY_AMBIGUITY"  # Java 返回多个可能的业务实体。
    UNSUPPORTED_CONDITION = "UNSUPPORTED_CONDITION"  # V1 无法执行某项条件。
    MESSAGE_INTENT = "MESSAGE_INTENT"  # 用户这句话的会话意图不明确。


class EntityKind(StrEnum):
    """由 Java 解析的业务字典类型。"""

    DEGREE = "DEGREE"  # 本科等学历层级。
    COMPANY = "COMPANY"  # 公司名称或公司标签。
    SCHOOL = "SCHOOL"  # 学校名称或学校标签。
    CITY = "CITY"  # 现居或期望城市标识。
    SCHOOL_LEVEL = "SCHOOL_LEVEL"  # 985、211、QS100 等院校等级标签。


class EntityResolutionStatus(StrEnum):
    """Java 对一个自然语言实体返回的解析状态。"""

    RESOLVED = "RESOLVED"  # 找到唯一权威实体。
    AMBIGUOUS = "AMBIGUOUS"  # 找到多个候选，需要用户澄清。
    NOT_FOUND = "NOT_FOUND"  # 没有找到可执行的业务实体。
