"""SearchPlan 确定性语义校验测试。"""

from talent_agent_py.application.plan_validation import (
    enforce_location_scope_clarification,
)
from talent_agent_py.domain.enums import LocationScope
from talent_agent_py.domain.plan import LocationCondition, SearchConditions, SearchPlanDraft


def test_bare_city_is_forced_back_to_location_clarification():
    """即使模型猜成现居地，裸城市也必须交给用户选择。"""

    draft = SearchPlanDraft(conditions=SearchConditions(
        current_city=LocationCondition(name="杭州", scope=LocationScope.CURRENT_CITY)
    ))

    normalized = enforce_location_scope_clarification(
        draft,
        ["找杭州的算法工程师"],
    )

    assert normalized.unresolved_location == "杭州"
    assert normalized.conditions.current_city is None
    assert normalized.conditions.expected_city is None


def test_explicit_current_city_is_not_changed():
    """用户明确说现居时应直接保留模型结果。"""

    draft = SearchPlanDraft(conditions=SearchConditions(
        current_city=LocationCondition(name="杭州", scope=LocationScope.CURRENT_CITY)
    ))

    normalized = enforce_location_scope_clarification(
        draft,
        ["找现居杭州的算法工程师"],
    )

    assert normalized == draft
