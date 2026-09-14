"""澄清卡和结构化答案测试。"""

import pytest

from talent_agent_py.application.clarification_service import (
    apply_location_answer,
    entity_not_found_card,
    location_scope_card,
)
from talent_agent_py.application.exceptions import InvalidClarificationAnswerError
from talent_agent_py.domain.conversation import ClarificationAnswer
from talent_agent_py.domain.plan import SearchPlanDraft


def test_location_answer_moves_unresolved_city_to_current_city():
    draft = SearchPlanDraft(unresolved_location="杭州")
    card = location_scope_card("杭州")
    result = apply_location_answer(
        draft,
        card,
        ClarificationAnswer(question_id=card.question_id, value="CURRENT_CITY"),
    )
    assert result.unresolved_location is None
    assert result.conditions.current_city.name == "杭州"


def test_clarification_rejects_forged_value():
    draft = SearchPlanDraft(unresolved_location="杭州")
    card = location_scope_card("杭州")
    with pytest.raises(InvalidClarificationAnswerError):
        apply_location_answer(
            draft,
            card,
            ClarificationAnswer(question_id=card.question_id, value="OTHER"),
        )


def test_entity_not_found_card_always_has_actionable_options():
    """Java 未找到实体时不能生成空选项卡片。"""

    card = entity_not_found_card(field="current_city", input_text="不存在的城市")

    assert {option.value for option in card.options} == {"IGNORE", "RESTATE"}
