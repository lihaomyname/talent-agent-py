"""固定澄清卡模板及结构化答案应用逻辑。"""

from uuid import uuid4

from talent_agent_py.application.exceptions import InvalidClarificationAnswerError
from talent_agent_py.domain.conversation import (
    ClarificationAnswer,
    ClarificationCard,
    ClarificationOption,
)
from talent_agent_py.domain.enums import ClarificationKind, ExperienceScope, LocationScope
from talent_agent_py.domain.plan import (
    LocationCondition,
    ResolvedEntity,
    SearchPlanDraft,
    UnsupportedCondition,
)


def _question_id() -> str:
    """生成新的澄清问题标识，供后续答案校验。"""

    return f"q_{uuid4().hex}"


def location_scope_card(location_name: str) -> ClarificationCard:
    """询问城市是现居地还是期望工作地。"""

    return ClarificationCard(
        question_id=_question_id(),
        kind=ClarificationKind.LOCATION_SCOPE,
        field="location.scope",
        title=f"“{location_name}”是指候选人的现居住地，还是期望工作地？",
        options=[
            ClarificationOption(value=LocationScope.CURRENT_CITY, label="现居住地"),
            ClarificationOption(value=LocationScope.EXPECTED_CITY, label="期望工作地"),
        ],
        context={"location_name": location_name},
    )


def experience_scope_card(*, field: str, value: str) -> ClarificationCard:
    """询问职位或公司是否只限制当前经历。"""

    kind = (
        ClarificationKind.POSITION_SCOPE
        if field == "candidate_position.scope"
        else ClarificationKind.COMPANY_SCOPE
    )
    noun = "职位" if kind is ClarificationKind.POSITION_SCOPE else "公司"
    return ClarificationCard(
        question_id=_question_id(),
        kind=kind,
        field=field,
        title=f"“{value}”只看当前{noun}，还是也包含历史{noun}？",
        options=[
            ClarificationOption(value=ExperienceScope.CURRENT, label=f"仅当前{noun}"),
            ClarificationOption(
                value=ExperienceScope.CURRENT_OR_HISTORY,
                label=f"当前或历史{noun}",
            ),
        ],
        context={"value": value},
    )


def unsupported_condition_card(condition: UnsupportedCondition) -> ClarificationCard:
    """明确说明 V1 不支持的硬条件，并要求用户选择。"""

    return ClarificationCard(
        question_id=_question_id(),
        kind=ClarificationKind.UNSUPPORTED_CONDITION,
        field="unsupported_conditions",
        title=f"目前不能直接按“{condition.original_text}”筛选，要忽略这个条件吗？",
        options=[
            ClarificationOption(value="IGNORE", label="忽略后继续"),
            ClarificationOption(value="RESTATE", label="重新描述条件"),
        ],
        context={"original_text": condition.original_text},
    )


def entity_ambiguity_card(
    *, field: str, options: list[ResolvedEntity]
) -> ClarificationCard:
    """把 Java 返回的多义实体转换成用户可选卡片。"""

    return ClarificationCard(
        question_id=_question_id(),
        kind=ClarificationKind.ENTITY_AMBIGUITY,
        field=field,
        title="找到多个可能的业务实体，请选择你想要的一个。",
        options=[
            ClarificationOption(value=option.code, label=option.label)
            for option in options
        ],
        context={"field": field},
    )


def entity_not_found_card(*, field: str, input_text: str | None) -> ClarificationCard:
    """实体未命中时给出可继续执行的选择，避免生成空选项卡片。"""

    shown_text = input_text or field
    return ClarificationCard(
        question_id=_question_id(),
        kind=ClarificationKind.ENTITY_NOT_FOUND,
        field=field,
        title=f"没有找到“{shown_text}”对应的可搜索项，要忽略这个条件吗？",
        options=[
            ClarificationOption(value="IGNORE", label="忽略后继续"),
            ClarificationOption(value="RESTATE", label="重新描述条件"),
        ],
        context={"field": field, "input_text": shown_text},
    )


def intent_card() -> ClarificationCard:
    """无法确认一句话是否修改搜索时使用。"""

    return ClarificationCard(
        question_id=_question_id(),
        kind=ClarificationKind.MESSAGE_INTENT,
        field="message.intent",
        title="你是想修改当前搜索条件吗？",
        options=[
            ClarificationOption(value="MODIFY_SEARCH", label="修改搜索"),
            ClarificationOption(value="CASUAL_CHAT", label="只是聊天"),
        ],
    )


def validate_answer(card: ClarificationCard, answer: ClarificationAnswer) -> None:
    """确保卡片没有串会话、过期或收到任意伪造值。"""

    allowed = {option.value for option in card.options}
    if answer.question_id != card.question_id or answer.value not in allowed:
        raise InvalidClarificationAnswerError("澄清问题或答案无效")


def apply_location_answer(
    draft: SearchPlanDraft,
    card: ClarificationCard,
    answer: ClarificationAnswer,
) -> SearchPlanDraft:
    """把未定范围的城市放入明确的当前或期望字段。"""

    validate_answer(card, answer)
    if card.kind is not ClarificationKind.LOCATION_SCOPE:
        raise InvalidClarificationAnswerError("澄清问题不是地点范围")
    location_name = card.context["location_name"]
    data = draft.model_dump(mode="python")
    data["unresolved_location"] = None
    data["ambiguities"] = [item for item in data["ambiguities"] if item["field"] != "location.scope"]
    target = "current_city" if answer.value == LocationScope.CURRENT_CITY else "expected_city"
    data["conditions"][target] = LocationCondition(
        name=location_name,
        scope=LocationScope(answer.value),
    ).model_dump(mode="python")
    return SearchPlanDraft.model_validate(data)


def apply_entity_answer(
    draft: SearchPlanDraft,
    card: ClarificationCard,
    answer: ClarificationAnswer,
) -> SearchPlanDraft:
    """把用户选中的 Java 权威实体写回对应条件。"""

    validate_answer(card, answer)
    if card.kind is not ClarificationKind.ENTITY_AMBIGUITY:
        raise InvalidClarificationAnswerError("澄清问题不是实体选择")
    selected = next(option for option in card.options if option.value == answer.value)
    entity = ResolvedEntity(code=selected.value, label=selected.label)
    data = draft.model_dump(mode="python")
    field = card.field

    if field == "minimum_degree":
        # 模糊学历的选项来自模型而非 Java，写回自然语言值并等待重新解析为权威 code。
        condition = data["conditions"].get("minimum_degree")
        if condition is None:
            data["conditions"]["minimum_degree"] = {"value": selected.label}
        else:
            condition["value"] = selected.label
            condition["resolved"] = None
    elif field in {"current_city", "expected_city"}:
        data["conditions"][field]["resolved"] = entity.model_dump(mode="python")
    elif ":" in field:
        field_name, _ = field.split(":", 1)
        condition = data["conditions"][field_name]
        condition.setdefault("resolved", []).append(entity.model_dump(mode="python"))
    else:
        raise InvalidClarificationAnswerError("无法应用该实体选择")

    data["ambiguities"] = [item for item in data["ambiguities"] if item["field"] != field]
    return SearchPlanDraft.model_validate(data)
