"""Java 人才搜索端口及其窄版契约。"""

from typing import Protocol

from pydantic import Field

from talent_agent_py.domain.base import StrictModel
from talent_agent_py.domain.conversation import CandidateCard, UserContext
from talent_agent_py.domain.enums import EntityKind, EntityResolutionStatus


class EntityResolutionRequest(StrictModel):
    """一个待 Java 解析的自然语言实体。"""

    key: str = Field(min_length=1, max_length=100)
    kind: EntityKind
    text: str = Field(min_length=1, max_length=200)


class EntityCandidate(StrictModel):
    """Java 返回的一个权威业务实体候选。"""

    code: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=200)


class EntityResolution(StrictModel):
    """单个实体的解析结果。"""

    key: str
    kind: EntityKind
    status: EntityResolutionStatus
    candidates: list[EntityCandidate] = Field(default_factory=list, max_length=20)


class FieldValue(StrictModel):
    """兼容 Java FieldValueForm 的受控值。"""

    type: str = Field(pattern="^(TEXT|LABEL)$")
    code: str | None = Field(default=None, max_length=128)
    value: str | None = Field(default=None, max_length=200)


class TalentSearchRequest(StrictModel):
    """V1 编译器唯一允许发送给 Java 的搜索字段。"""

    applicantName: str | None = None
    strictApplicantName: bool = True
    nowPosition: str | None = None
    onlyNowPosition: bool = False
    topDegree: str | None = None
    workYearsMin: int | None = Field(default=None, ge=0, le=60)
    workYearsMax: int | None = Field(default=None, ge=0, le=60)
    nowCompany: list[FieldValue] = Field(default_factory=list, max_length=20)
    onlyNowCompany: bool = False
    school: list[FieldValue] = Field(default_factory=list, max_length=20)
    livePlace: list[int] = Field(default_factory=list, max_length=20)
    expectWorkPlace: list[str] = Field(default_factory=list, max_length=20)
    schoolLevelList: list[FieldValue] = Field(default_factory=list, max_length=20)
    firstDegree: bool = False
    currentPage: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=100)
    sortType: int = 1
    keyWordsMatchType: str = Field(default="ALL", pattern="^(ALL|ANY)$")
    inFlow: bool = True
    hideClue: bool = True


class TalentSearchResponse(StrictModel):
    """Java 返回的安全人才卡及分页信息。"""

    candidates: list[CandidateCard] = Field(default_factory=list)
    total: int = Field(ge=0)
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
