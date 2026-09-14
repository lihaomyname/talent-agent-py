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


def test_vague_degree_answer_creates_condition_waiting_for_resolution():
    """模糊学历澄清后应写入自然语言值，等待 Java 解析为权威 code。"""

    from talent_agent_py.application.clarification_service import (
        apply_entity_answer,
        entity_ambiguity_card,
    )
    from talent_agent_py.domain.plan import Ambiguity, ResolvedEntity

    ambiguity = Ambiguity(
        field="minimum_degree",
        reason="用户表达为模糊学历",
        options=["本科", "硕士", "博士"],
    )
    draft = SearchPlanDraft.model_validate(
        {"conditions": {}, "ambiguities": [ambiguity.model_dump(mode="python")]}
    )
    card = entity_ambiguity_card(
        field="minimum_degree",
        options=[
            ResolvedEntity(code=option, label=option)
            for option in ["本科", "硕士", "博士"]
        ],
    )

    result = apply_entity_answer(
        draft, card, ClarificationAnswer(question_id=card.question_id, value="硕士")
    )

    assert result.conditions.minimum_degree is not None
    assert result.conditions.minimum_degree.value == "硕士"
    assert result.conditions.minimum_degree.resolved is None
    assert result.ambiguities == []


def test_vague_degree_answer_replaces_existing_degree_and_clears_resolution():
    from talent_agent_py.application.clarification_service import (
        apply_entity_answer,
        entity_ambiguity_card,
    )
    from talent_agent_py.domain.plan import Ambiguity, ResolvedEntity

    draft = SearchPlanDraft.model_validate({
        "conditions": {"minimum_degree": {"value": "大专", "resolved": {"code": "05", "label": "大专"}}},
        "ambiguities": [Ambiguity(
            field="minimum_degree",
            reason="用户表达为模糊学历",
            options=["本科", "硕士", "博士"],
        ).model_dump(mode="python")],
    })
    card = entity_ambiguity_card(
        field="minimum_degree",
        options=[ResolvedEntity(code=option, label=option) for option in ["本科", "硕士", "博士"]],
    )

    result = apply_entity_answer(
        draft, card, ClarificationAnswer(question_id=card.question_id, value="博士")
    )

    assert result.conditions.minimum_degree.value == "博士"
    assert result.conditions.minimum_degree.resolved is None


def test_prompts_require_closed_options_for_vague_degree():
    """提示词必须约束模糊学历表达，不能让模型自行猜测学历。"""

    from talent_agent_py.infrastructure.clients.prompts import (
        PATCH_SYSTEM_PROMPT,
        PLAN_SYSTEM_PROMPT,
    )

    for prompt in (PLAN_SYSTEM_PROMPT, PATCH_SYSTEM_PROMPT):
        assert "学历高" in prompt
        assert '"本科", "硕士", "博士"' in prompt
