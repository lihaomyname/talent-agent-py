"""偏好匹配使用的候选资料和模型证据。"""

from typing import Literal

from pydantic import Field

from talent_agent_py.domain.base import StrictModel
from talent_agent_py.domain.conversation import CandidateCard


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
