"""不依赖模型的 SearchPlan 业务校验。"""

from dataclasses import dataclass

from talent_agent_py.domain.enums import LocationScope
from talent_agent_py.domain.plan import Ambiguity, SearchPlanDraft


@dataclass(frozen=True)
class ValidationOutcome:
    """校验结果；errors 表示不可恢复错误，ambiguities 表示需用户选择。"""

    errors: tuple[str, ...] = ()
    ambiguities: tuple[Ambiguity, ...] = ()

    @property
    def executable(self) -> bool:
        """只有无错误、无歧义、无未处理硬条件时才可执行。"""

        return not self.errors and not self.ambiguities


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
