"""招聘资料白名单及证据校验，避免把宽响应直接交给模型。"""

import re

from talent_agent_py.domain.conversation import CandidateCard, ExperienceView
from talent_agent_py.domain.matching import (
    CandidateEvaluation,
    CandidateProfile,
    MatchEvidence,
    ProfileSource,
)
from talent_agent_py.domain.plan import Preference


def clean_profile_text(value: object) -> str:
    text = str(value or "").replace("\x00", "")
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}", "[邮箱已隐藏]", text)
    text = re.sub(r"(?<!\d)\+?\d[\d -]{9,}\d(?!\d)", "[号码已隐藏]", text)
    return text.strip()


def build_experience_views(item: dict) -> list[ExperienceView]:
    """把招聘接口的经历记录整理成页面可以直接阅读的条目。"""

    views: list[ExperienceView] = []
    groups = (
        ("resumeWorkExpList", "WORK", ("company", "position"), ("detail", "duty")),
        ("resumeEducationList", "EDUCATION", ("schoolName", "majorName", "degreeName"), ()),
    )
    for group, category, title_fields, detail_fields in groups:
        records = item.get(group) or []
        if not isinstance(records, list):
            continue
        for index, record in enumerate(records[:20]):
            if not isinstance(record, dict):
                continue
            title = " · ".join(
                value for field in title_fields if (value := clean_profile_text(record.get(field)))
            )
            start = clean_profile_text(record.get("startDate"))
            end = clean_profile_text(record.get("endDate")) or "至今"
            period = " — ".join(value for value in (start, end) if value)
            details: list[str] = []
            for field in detail_fields:
                value = clean_profile_text(record.get(field))
                if value and value not in details:
                    details.append(value)
            lines = [value for value in (title, period, *details) if value]
            if lines:
                views.append(
                    ExperienceView(
                        category=category,
                        path=f"{group}.{index}",
                        text="\n".join(lines),
                    )
                )
    return views


def build_candidate_profile(item: dict, card: CandidateCard, page: int) -> CandidateProfile:
    sources = []
    incomplete = False
    for key in ("topDegreeName", "livePlaceName", "expectWorkPlaceName", "resumeUpdateTime"):
        if item.get(key):
            sources.append(ProfileSource(path=key, text=clean_profile_text(item[key])[:6000]))
    groups = {
        "resumeEducationList": ("schoolName", "majorName", "degreeName", "startDate", "endDate"),
        "resumeWorkExpList": ("position", "company", "startDate", "endDate", "detail", "duty"),
    }
    for group, fields in groups.items():
        records = item.get(group) or []
        if not isinstance(records, list):
            incomplete = True
            continue
        if len(records) > 20:
            incomplete = True
        for index, record in enumerate(records[:20]):
            if not isinstance(record, dict):
                incomplete = True
                continue
            for field in fields:
                if field == "duty" and record.get("duty") == record.get("detail"):
                    continue
                raw = clean_profile_text(record.get(field))
                if not raw:
                    continue
                if len(sources) >= 160:
                    incomplete = True
                    break
                sources.append(
                    ProfileSource(
                        path=f"{group}.{index}.{field}",
                        text=raw[:6000],
                        truncated=len(raw) > 6000,
                    )
                )
    return CandidateProfile(
        candidate_id=card.candidate_id,
        card=card,
        source_page=page,
        sources=sources,
        incomplete=incomplete or not item.get("resumeWorkExpList"),
    )


def validate_evaluation(
    evaluation: CandidateEvaluation,
    profile: CandidateProfile,
    preferences: list[Preference] | tuple[Preference, ...],
) -> None:
    expected = {item.id for item in preferences}
    ids = [item.criterion_id for item in evaluation.evidence]
    if (
        evaluation.candidate_id != profile.candidate_id
        or set(ids) != expected
        or len(ids) != len(expected)
    ):
        raise ValueError("候选人或要求 ID 不一致")
    sources = {source.path: source.text for source in profile.sources}
    for evidence in evaluation.evidence:
        # UNKNOWN 也不能携带虚构引用；只有完全未引用时允许无来源。
        has_reference = evidence.quote is not None or evidence.source_path is not None
        requires_reference = evidence.status != "UNKNOWN" or has_reference
        if requires_reference and (
            not evidence.quote or evidence.quote not in sources.get(evidence.source_path, "")
        ):
            raise ValueError("匹配证据引用不存在")


def failed_evaluation(
    profile: CandidateProfile, preferences: list[Preference] | tuple[Preference, ...]
) -> CandidateEvaluation:
    return CandidateEvaluation(
        candidate_id=profile.candidate_id,
        failed=True,
        evidence=[
            MatchEvidence(
                criterion_id=item.id,
                status="UNKNOWN",
                explanation="评估未完成，不能确认满足要求",
            )
            for item in preferences
        ],
    )


def evaluation_rank(
    evaluation: CandidateEvaluation, preferences: list[Preference] | tuple[Preference, ...]
) -> tuple:
    by_id = {item.criterion_id: item.status for item in evaluation.evidence}
    if evaluation.failed:
        return (False, False, 0, 0)
    preferred = [by_id.get(item.id, "UNKNOWN") for item in preferences]
    supported_count = preferred.count("SUPPORTED")
    partial_count = preferred.count("PARTIAL")
    return (supported_count + partial_count > 0, False, supported_count, partial_count)
