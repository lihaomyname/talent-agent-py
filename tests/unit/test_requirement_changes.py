import pytest

from talent_agent_py.application.requirement_changes import apply_requirement_change
from talent_agent_py.domain.matching import MatchCriterion, RequirementChange, SearchRequirements
from talent_agent_py.domain.plan import PositionCondition, SearchConditions


def initial():
    return SearchRequirements(conditions=SearchConditions(candidate_position=PositionCondition(value="战斗策划")),
        preferences=[MatchCriterion(id="ugc", description="UGC经验", source_quote="UGC优先")])


def test_filter_change_preserves_preference_and_omitted_filters():
    change = RequirementChange.model_validate({"source_text": "只看本科", "filters_patch": {
        "base_plan_version": 1, "operations": [{"operation": "REPLACE", "field": "minimum_degree",
                                               "value": {"value": "本科"}}],
    }}, strict=False)
    updated = apply_requirement_change(initial(), change, 1)
    assert updated.preferences == initial().preferences
    assert updated.conditions.candidate_position == initial().conditions.candidate_position
    assert updated.conditions.minimum_degree.value == "本科"
    assert updated.needs_matching()


def test_explicit_remove_last_preference_returns_simple_mode():
    change = RequirementChange.model_validate({"source_text": "去掉UGC优先", "criterion_edits": [{
        "operation": "REMOVE", "group": "preferences", "criterion_id": "ugc",
    }]})
    updated = apply_requirement_change(initial(), change, 1)
    assert not updated.needs_matching()
    assert updated.conditions == initial().conditions


def test_non_job_image_keeps_requirement_and_requires_clarification():
    result = apply_requirement_change(initial(), RequirementChange(source_text="无法识别", is_job_request=False), 1)
    assert result.ambiguities
    assert result.preferences == initial().preferences


def test_unknown_criterion_cannot_be_silently_removed():
    change = RequirementChange.model_validate({"source_text": "删除", "criterion_edits": [{
        "operation": "REMOVE", "group": "preferences", "criterion_id": "missing",
    }]})
    with pytest.raises(ValueError):
        apply_requirement_change(initial(), change, 1)


def test_non_filter_requirements_are_forced_to_preferences():
    change = RequirementChange.model_validate({"source_text": "熟悉 Java，沟通能力强", "criterion_edits": [
        {"operation": "ADD", "group": "required_criteria", "criterion_id": "java",
         "value": {"id": "java", "description": "熟悉 Java", "source_quote": "熟悉 Java"}},
        {"operation": "ADD", "group": "interview_items", "criterion_id": "communication",
         "value": {"id": "communication", "description": "沟通能力强", "source_quote": "沟通能力强"}},
    ]})
    updated = apply_requirement_change(SearchRequirements(), change, 0)
    assert updated.required_criteria == []
    assert updated.interview_items == []
    assert [item.id for item in updated.preferences] == ["java", "communication"]
