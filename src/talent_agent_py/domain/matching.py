"""匹配需求、候选证据及复用现有 JSON 列的 V2 快照。"""

from typing import Literal

from pydantic import Field, model_validator

from talent_agent_py.domain.base import StrictModel
from talent_agent_py.domain.conversation import CandidateCard
from talent_agent_py.domain.plan import PlanPatch, SearchConditions, SearchPlan


class OwnerScope(StrictModel):
    """快照的归属；不能由模型提供。"""

    user_id: str
    tenant_id: str | None = None
    session_id: str


class MatchCriterion(StrictModel):
    """一项要求及用户原文，不包含模型自定权重。"""

    id: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=500)
    source_quote: str = Field(min_length=1, max_length=500)


class SearchRequirements(StrictModel):
    """完整语义基准，修改时必须保留未提及部分。"""

    source_text: str = Field(default="", max_length=20000)
    conditions: SearchConditions = Field(default_factory=SearchConditions)
    required_criteria: list[MatchCriterion] = Field(default_factory=list, max_length=20)
    preferences: list[MatchCriterion] = Field(default_factory=list, max_length=20)
    interview_items: list[MatchCriterion] = Field(default_factory=list, max_length=20)
    ambiguities: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique_criteria(self) -> "SearchRequirements":
        ids = [item.id for item in self.required_criteria + self.preferences + self.interview_items]
        if len(ids) != len(set(ids)):
            raise ValueError("要求 ID 不能重复")
        return self

    def needs_matching(self) -> bool:
        return bool(self.required_criteria or self.preferences)


class CriterionEdit(StrictModel):
    """显式增删改；不通过遗漏字段表示删除。"""

    operation: Literal["ADD", "REPLACE", "REMOVE"]
    group: Literal["required_criteria", "preferences", "interview_items"]
    criterion_id: str = Field(min_length=1, max_length=64)
    value: MatchCriterion | None = None

    @model_validator(mode="after")
    def check_value(self) -> "CriterionEdit":
        if self.operation == "REMOVE" and self.value is not None:
            raise ValueError("删除要求不携带新值")
        if self.operation != "REMOVE" and (
            self.value is None or self.value.id != self.criterion_id
        ):
            raise ValueError("新增或修改要求需要一致的 ID 和内容")
        return self


class RequirementChange(StrictModel):
    """模型返回的需求变更；图片先读原文再填变更。"""

    source_text: str = Field(max_length=20000)
    is_job_request: bool = True
    filters_patch: PlanPatch | None = None
    criterion_edits: list[CriterionEdit] = Field(default_factory=list, max_length=60)
    ambiguities: list[str] = Field(default_factory=list, max_length=20)


class ProfileSource(StrictModel):
    """清洗后可引用的字段；路径指向原招聘响应中的经历位置。"""

    path: str
    text: str = Field(max_length=6000)
    truncated: bool = False


class CandidateProfile(StrictModel):
    candidate_id: str
    card: CandidateCard
    sources: list[ProfileSource] = Field(default_factory=list, max_length=160)
    source_page: int = Field(ge=1)
    incomplete: bool = False


class CandidateProfilePage(StrictModel):
    candidates: list[CandidateProfile] = Field(default_factory=list, max_length=10)
    total: int = Field(ge=0)
    has_next: bool = False


class MatchEvidence(StrictModel):
    criterion_id: str
    status: Literal["SUPPORTED", "PARTIAL", "UNKNOWN", "CONTRADICTED"]
    source_path: str | None = None
    quote: str | None = Field(default=None, max_length=600)
    explanation: str = Field(max_length=1000)


class CandidateEvaluation(StrictModel):
    candidate_id: str
    evidence: list[MatchEvidence] = Field(default_factory=list, max_length=40)
    failed: bool = False


class EvaluationBatch(StrictModel):
    evaluations: list[CandidateEvaluation] = Field(max_length=5)


class MatchingBudget(StrictModel):
    target: int = Field(default=10, ge=1, le=10)
    max_pages: int = Field(default=5, ge=1)
    max_candidates: int = Field(default=50, ge=1)
    max_model_attempts: int = Field(default=20, ge=1)
    batch_size: int = Field(default=5, ge=1, le=5)
    deadline_seconds: float = Field(default=120, gt=0)


class MatchingUsage(StrictModel):
    search_calls: int = 0
    checked_candidates: int = 0
    model_attempts: int = 0
    elapsed_seconds: float = 0


class MatchingCheckpoint(StrictModel):
    """每个小批完成后整体赋值保存，避免嵌套 JSON 修改未被追踪。"""

    next_page: int = 1
    buffered: list[CandidateProfile] = Field(default_factory=list, max_length=10)
    profiles: dict[str, CandidateProfile] = Field(default_factory=dict)
    evaluations: dict[str, CandidateEvaluation] = Field(default_factory=dict)
    checked_ids: list[str] = Field(default_factory=list)
    displayed_ids: list[str] = Field(default_factory=list)
    source_exhausted: bool = False
    round_number: int = 1


class MatchingPlanSnapshot(StrictModel):
    schema_version: Literal[2] = 2
    kind: Literal["matching_plan"] = "matching_plan"
    owner_scope: OwnerScope
    requirements: SearchRequirements
    search_plan: SearchPlan


class MatchingDraftSnapshot(StrictModel):
    schema_version: Literal[2] = 2
    kind: Literal["matching_draft"] = "matching_draft"
    owner_scope: OwnerScope
    requirements: SearchRequirements
    base_plan_version: int
    requirement_id: str
    source_message_sequence: int
    input_type: Literal["text", "image"] = "text"


class MatchingRunSnapshot(StrictModel):
    schema_version: Literal[2] = 2
    kind: Literal["matching_run"] = "matching_run"
    owner_scope: OwnerScope
    plan_version: int
    parent_run_id: str | None = None
    continuation_root_run_id: str
    request_key: str
    budget: MatchingBudget
    usage: MatchingUsage = Field(default_factory=MatchingUsage)
    checkpoint: MatchingCheckpoint = Field(default_factory=MatchingCheckpoint)
    stop_reason: str | None = None
    output_group: list[str] = Field(default_factory=list, max_length=10)
    pending_group: list[str] = Field(default_factory=list, max_length=10)


class MatchingReplySnapshot(StrictModel):
    """历史仅放引用，候选资料须经授权端点加载。"""

    schema_version: Literal[2] = 2
    kind: Literal["matching_reply"] = "matching_reply"
    owner_scope: OwnerScope
    run_id: str | None = None
    requirement_id: str | None = None
    plan_version: int = 0
