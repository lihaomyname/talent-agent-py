"""不依赖模型的 SearchPlan 业务校验。"""

from dataclasses import dataclass

from talent_agent_py.domain.enums import LocationScope
from talent_agent_py.domain.plan import (
    Ambiguity,
    SearchConditions,
    SearchPlanDraft,
)

# 这些词能够明确地点字段；单独出现“杭州”“上海”等城市名时必须询问用户。
_CURRENT_LOCATION_CUES = ("现居", "居住", "住在", "人在", "目前在", "当前在", "所在地")
_EXPECTED_LOCATION_CUES = ("期望", "意向", "希望在", "想去", "工作地", "工作地点")


@dataclass(frozen=True)
class ValidationOutcome:
    """校验结果；errors 表示不可恢复错误，ambiguities 表示需用户选择。"""

    # 阻塞搜索的错误码，例如 EMPTY_SEARCH_PLAN。
    errors: tuple[str, ...] = ()
    # 需要用户选择的歧义；为空才可能继续执行。
    ambiguities: tuple[Ambiguity, ...] = ()

    @property
    def executable(self) -> bool:
        """只有无错误、无歧义、无未处理硬条件时才可执行。"""

        return not self.errors and not self.ambiguities


def enforce_location_scope_clarification(
    draft: SearchPlanDraft,
    messages: list[str],
    *,
    previous_conditions: SearchConditions | None = None,
) -> SearchPlanDraft:
    """模型猜测地点范围时回退为澄清，避免把裸城市默认为现居地。"""

    if draft.unresolved_location:
        return draft
    text = " ".join(messages)
    if any(cue in text for cue in (*_CURRENT_LOCATION_CUES, *_EXPECTED_LOCATION_CUES)):
        return draft
    # 修改已有计划时，“杭州改成上海”可以沿用已经确定的地点范围。
    if previous_conditions and (
        previous_conditions.current_city or previous_conditions.expected_city
    ):
        return draft

    locations = [
        ("current_city", draft.conditions.current_city),
        ("expected_city", draft.conditions.expected_city),
    ]
    present = [(field, condition) for field, condition in locations if condition]
    if len(present) != 1:
        return draft

    field, condition = present[0]
    data = draft.model_dump(mode="python")
    data["conditions"][field] = None
    data["unresolved_location"] = condition.name
    return SearchPlanDraft.model_validate(data)


def validate_draft(draft: SearchPlanDraft) -> ValidationOutcome:
    """执行范围和语义校验，禁止模型绕过业务约束。"""

    errors: list[str] = []
    ambiguities = list(draft.ambiguities)
    conditions = draft.conditions

    if draft.unresolved_location:
        ambiguities.append(
            Ambiguity(
                field="location.scope",
                reason="地点未说明是现居住地还是期望工作地",
                options=["CURRENT_CITY", "EXPECTED_CITY"],
            )
        )

    for location_field in (conditions.current_city, conditions.expected_city):
        if location_field and location_field.scope is LocationScope.UNKNOWN:
            ambiguities.append(
                Ambiguity(
                    field="location.scope",
                    reason="地点未说明是现居住地还是期望工作地",
                    options=["CURRENT_CITY", "EXPECTED_CITY"],
                )
            )

    if draft.unsupported_conditions:
        errors.append("UNSUPPORTED_CONDITION")

    if not draft.unresolved_location and not any(
        value is not None for value in conditions.model_dump().values()
    ):
        errors.append("EMPTY_SEARCH_PLAN")

    return ValidationOutcome(tuple(errors), tuple(ambiguities))
