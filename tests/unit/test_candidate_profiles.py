import pytest

from talent_agent_py.application.candidate_profiles import (
    build_candidate_profile,
    evaluation_rank,
    validate_evaluation,
)
from talent_agent_py.domain.conversation import CandidateCard
from talent_agent_py.domain.matching import (
    CandidateEvaluation,
    MatchCriterion,
    MatchEvidence,
    SearchRequirements,
)


def test_profile_whitelist_deduplicates_and_redacts_contacts():
    raw = {
        "resumeBaseAppMobile": "13800138000",
        "resumeBaseAppEmail": "private@example.com",
        "resumeWorkExpList": [{
            "position": "战斗策划",
            "detail": "UGC 编辑器，联系 private@example.com 13800138000",
            "duty": "UGC 编辑器，联系 private@example.com 13800138000",
        }],
    }
    profile = build_candidate_profile(raw, CandidateCard(candidate_id="a"), 1)
    sources = {source.path: source.text for source in profile.sources}
    assert "resumeWorkExpList.0.duty" not in sources
    assert "private@example.com" not in str(sources)
    assert "13800138000" not in str(sources)
    assert "resumeBaseAppMobile" not in sources


def test_missing_experience_keeps_card_and_marks_incomplete():
    card = CandidateCard(candidate_id="a", display_name="测试")
    profile = build_candidate_profile({}, card, 1)
    assert profile.card == card
    assert profile.incomplete


@pytest.mark.parametrize("status", ["SUPPORTED", "PARTIAL", "UNKNOWN", "CONTRADICTED"])
def test_fabricated_quote_rejected_even_for_unknown(status):
    profile = build_candidate_profile({}, CandidateCard(candidate_id="a"), 1)
    requirements = SearchRequirements(required_criteria=[
        MatchCriterion(id="hard", description="射击调优", source_quote="必须有射击调优"),
    ])
    evaluation = CandidateEvaluation(candidate_id="a", evidence=[
        MatchEvidence(criterion_id="hard", status=status, source_path="invented",
                      quote="枪械调优", explanation="测试"),
    ])
    with pytest.raises(ValueError, match="引用不存在"):
        validate_evaluation(evaluation, profile, requirements)


@pytest.mark.parametrize("status,eligible,pending", [
    ("SUPPORTED", True, False), ("PARTIAL", False, True),
    ("UNKNOWN", False, True), ("CONTRADICTED", False, False),
])
def test_hard_requirement_admission_and_optional_preference(status, eligible, pending):
    requirements = SearchRequirements(
        required_criteria=[MatchCriterion(id="hard", description="射击", source_quote="必须射击")],
        preferences=[MatchCriterion(id="soft", description="UGC", source_quote="UGC优先")],
    )
    evaluation = CandidateEvaluation(candidate_id="a", evidence=[
        MatchEvidence(criterion_id="hard", status=status, explanation="测试"),
        MatchEvidence(criterion_id="soft", status="UNKNOWN", explanation="未提及"),
    ])
    assert evaluation_rank(evaluation, requirements) == (eligible, pending, 0, 0)


def test_unknown_language_preference_never_eliminates_candidate():
    requirements = SearchRequirements(preferences=[
        MatchCriterion(id="java", description="熟悉 Java", source_quote="熟悉 Java"),
    ])
    evaluation = CandidateEvaluation(candidate_id="a", evidence=[
        MatchEvidence(criterion_id="java", status="UNKNOWN", explanation="教育和工作经历未提及"),
    ])
    assert evaluation_rank(evaluation, requirements) == (True, False, 0, 0)
