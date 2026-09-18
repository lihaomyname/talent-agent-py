"""Java 人才搜索端口及其窄版契约。"""

from typing import Protocol

from pydantic import Field

from talent_agent_py.domain.base import StrictModel
from talent_agent_py.domain.conversation import CandidateCard, UserContext
from talent_agent_py.domain.enums import EntityKind, EntityResolutionStatus
from talent_agent_py.domain.matching import CandidateProfilePage


class EntityResolutionRequest(StrictModel):
    """一个待 Java 解析的自然语言实体。"""

    # 回填草稿的字段路径，例如 company:0。
    key: str = Field(min_length=1, max_length=100)
    # 要查询的业务实体类型。
    kind: EntityKind
    # 需要解析的自然语言名称。
    text: str = Field(min_length=1, max_length=200)


class EntityCandidate(StrictModel):
    """Java 返回的一个权威业务实体候选。"""

    # 招聘系统返回的业务编码，不能由模型自行编造。
    code: str = Field(min_length=1, max_length=128)
    # 供用户阅读的实体或选项名称。
    label: str = Field(min_length=1, max_length=200)


class EntityResolution(StrictModel):
    """单个实体的解析结果。"""

    # 对应请求的字段路径，用于定位回填位置。
    key: str
    # 本次解析的实体类别。
    kind: EntityKind
    # 唯一命中、多义或未找到。
    status: EntityResolutionStatus
    # 权威候选列表；唯一解析应只有一个结果。
    candidates: list[EntityCandidate] = Field(default_factory=list, max_length=20)


class FieldValue(StrictModel):
    """兼容 Java FieldValueForm 的受控值。"""

    # TEXT 表示文本条件，LABEL 表示业务编码条件。
    type: str = Field(pattern="^(TEXT|LABEL)$")
    # LABEL 条件的业务编码；文本条件可为空。
    code: str | None = Field(default=None, max_length=128)
    # TEXT 条件的文本；编码条件可为空。
    value: str | None = Field(default=None, max_length=200)


class TalentSearchRequest(StrictModel):
    """V1 编译器唯一允许发送给 Java 的搜索字段。"""

    # 候选人姓名；为空表示不限制。
    applicantName: str | None = None
    # 是否精确匹配姓名。
    strictApplicantName: bool = True
    # 候选人职位名称，范围由 onlyNowPosition 控制。
    nowPosition: str | None = None
    # True 仅当前职位，False 包含历史职位。
    onlyNowPosition: bool = False
    # 最低学历业务编码，由学历解析提供。
    topDegree: str | None = None
    # 总工作年限下限，单位年；为空表示不限制。
    workYearsMin: int | None = Field(default=None, ge=0, le=60)
    # 总工作年限上限，单位年；为空表示不限制。
    workYearsMax: int | None = Field(default=None, ge=0, le=60)
    # 公司条件列表，支持接口约定的文本或标签结构。
    nowCompany: list[FieldValue] = Field(default_factory=list, max_length=20)
    # True 仅当前公司，False 包含历史公司。
    onlyNowCompany: bool = False
    # 学校条件列表，使用招聘接口的 FieldValue 结构。
    school: list[FieldValue] = Field(default_factory=list, max_length=20)
    # 现居住地编码，招聘接口要求整数列表。
    livePlace: list[int] = Field(default_factory=list, max_length=20)
    # 期望工作地编码，招聘接口要求字符串列表。
    expectWorkPlace: list[str] = Field(default_factory=list, max_length=20)
    # 院校等级标签列表。
    schoolLevelList: list[FieldValue] = Field(default_factory=list, max_length=20)
    # 是否只在第一学历中匹配院校标签。
    firstDegree: bool = False
    # 目标页码，从 1 开始。
    currentPage: int = Field(default=1, ge=1)
    # 分页大小由 Agent 控制，调用方和模型都不能扩大到 10 条以上。
    pageSize: int = Field(default=10, ge=1, le=10)
    # 招聘接口排序策略编码，由服务端配置决定。
    sortType: int = 1
    # 多关键词匹配方式：ALL 或 ANY。
    keyWordsMatchType: str = Field(default="ALL", pattern="^(ALL|ANY)$")
    # 透传招聘接口的 inFlow 策略，由服务端配置决定。
    inFlow: bool = True
    # 透传招聘接口的线索隐藏策略，由服务端配置决定。
    hideClue: bool = True


class TalentSearchResponse(StrictModel):
    """Java 返回的安全人才卡及分页信息。"""

    # 本页候选人卡片，最多 10 条。
    candidates: list[CandidateCard] = Field(default_factory=list, max_length=10)
    # 招聘接口报告的总命中数。
    total: int = Field(ge=0)
    # 是否还有下一页，供服务端生成分页引用。
    has_next: bool = False


class TalentSearchPort(Protocol):
    """Java 权威实体解析和人才检索能力。"""

    async def resolve_entities(
        self,
        requests: list[EntityResolutionRequest],
        user: UserContext,
    ) -> list[EntityResolution]:
        """解析学历、公司、学校、城市和院校标签。"""

    async def search_candidates(
        self,
        request: TalentSearchRequest,
        user: UserContext,
    ) -> TalentSearchResponse:
        """在 Java 权限边界内搜索并返回脱敏人才卡。"""

    async def search_candidate_profiles(
        self,
        request: TalentSearchRequest,
        user: UserContext,
    ) -> CandidateProfilePage:
        """同一权限与分页契约下读取白名单资料，仅供证据匹配使用。"""
