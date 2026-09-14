"""版本化人才搜索计划及其支持条件。"""

from __future__ import annotations

from typing import Any

from pydantic import Field, JsonValue, model_validator

from talent_agent_py.domain.base import StrictModel
from talent_agent_py.domain.enums import (
    ExperienceScope,
    LocationScope,
    NameMatchMode,
    PatchOperation,
    SupportedField,
)


class ResolvedEntity(StrictModel):
    """Java 权威标识和安全展示名称。"""

    code: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=200)


class ApplicantNameCondition(StrictModel):
    """候选人姓名条件。"""

    value: str = Field(min_length=1, max_length=100)
    match_mode: NameMatchMode = NameMatchMode.EXACT


class PositionCondition(StrictModel):
    """候选人简历职位，与招聘职位 ID 无关。"""

    value: str = Field(min_length=1, max_length=200)
    scope: ExperienceScope = ExperienceScope.CURRENT_OR_HISTORY


class DegreeCondition(StrictModel):
    """最低学历语义值，以及可选的 Java 解析结果。"""

    value: str = Field(min_length=1, max_length=50)
    resolved: ResolvedEntity | None = None


class WorkYearsCondition(StrictModel):
    """面向招聘人员表达的总工作年限范围。"""

    minimum: int | None = Field(default=None, ge=0, le=60)
    maximum: int | None = Field(default=None, ge=0, le=60)

    @model_validator(mode="after")
    def validate_range(self) -> WorkYearsCondition:
        if self.minimum is None and self.maximum is None:
            raise ValueError("work years requires a minimum or maximum")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("work years minimum cannot exceed maximum")
        return self


class CompanyCondition(StrictModel):
    """共享当前/历史范围的一组公司。"""

    names: list[str] = Field(min_length=1, max_length=20)
    scope: ExperienceScope = ExperienceScope.CURRENT_OR_HISTORY
    resolved: list[ResolvedEntity] = Field(default_factory=list, max_length=20)


class SchoolCondition(StrictModel):
    """由 Java 解析的一组学校。"""

    names: list[str] = Field(min_length=1, max_length=20)
    resolved: list[ResolvedEntity] = Field(default_factory=list, max_length=20)


class LocationCondition(StrictModel):
    """一个城市及其现居/期望语义。"""

    name: str = Field(min_length=1, max_length=100)
    scope: LocationScope
    resolved: ResolvedEntity | None = None


class SchoolLevelCondition(StrictModel):
    """院校等级标签和第一学历限制。"""

    labels: list[str] = Field(min_length=1, max_length=20)
    first_degree_only: bool = False
    resolved: list[ResolvedEntity] = Field(default_factory=list, max_length=20)


class SearchConditions(StrictModel):
    """V1 可执行条件的完整集合。"""

    applicant_name: ApplicantNameCondition | None = None
    candidate_position: PositionCondition | None = None
    minimum_degree: DegreeCondition | None = None
    work_years: WorkYearsCondition | None = None
    company: CompanyCondition | None = None
    school: SchoolCondition | None = None
    expected_city: LocationCondition | None = None
    current_city: LocationCondition | None = None
    school_level: SchoolLevelCondition | None = None

    @model_validator(mode="after")
    def validate_location_scopes(self) -> SearchConditions:
        if self.current_city and self.current_city.scope is not LocationScope.CURRENT_CITY:
            raise ValueError("current_city must use CURRENT_CITY scope")
        if self.expected_city and self.expected_city.scope is not LocationScope.EXPECTED_CITY:
            raise ValueError("expected_city must use EXPECTED_CITY scope")
        return self


class UnsupportedCondition(StrictModel):
    """模型能够理解、但 V1 无法执行的用户条件。"""

    original_text: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)
    hard_requirement: bool = True


class Ambiguity(StrictModel):
    """搜索前发现的阻塞性语义选择。"""

    field: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(default_factory=list, max_length=20)
    entity_options: list[ResolvedEntity] = Field(default_factory=list, max_length=20)
    input_text: str | None = Field(default=None, min_length=1, max_length=200)


class SearchPlanDraft(StrictModel):
    """Java 实体解析前的语义草稿。"""

    schema_version: int = 1
    conditions: SearchConditions = Field(default_factory=SearchConditions)
    unresolved_location: str | None = Field(default=None, min_length=1, max_length=100)
    unsupported_conditions: list[UnsupportedCondition] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)


class PlanPatchItem(StrictModel):
    """后续用户轮次请求的一项计划修改。"""

    operation: PatchOperation
    field: SupportedField | None = None
    value: JsonValue | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> PlanPatchItem:
        if self.operation is PatchOperation.RESET:
            if self.field is not None or self.value is not None:
                raise ValueError("RESET cannot target a field or carry a value")
        elif self.field is None:
            raise ValueError("non-RESET operation requires a field")
        elif self.operation in {PatchOperation.ADD, PatchOperation.REPLACE} and self.value is None:
            raise ValueError("ADD and REPLACE require a value")
        return self


class PlanPatch(StrictModel):
    """模型针对已提交 SearchPlan 生成的增量修改。"""

    schema_version: int = 1
    base_plan_version: int = Field(ge=0)
    operations: list[PlanPatchItem] = Field(min_length=1, max_length=30)
    unsupported_conditions: list[UnsupportedCondition] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)


class SearchPlan(StrictModel):
    """不可变、可执行且可审计的搜索计划。"""

    model_config = StrictModel.model_config | {"frozen": True}

    schema_version: int = 1
    version: int = Field(ge=1)
    applied_through_message_seq: int = Field(ge=0)
    conditions: SearchConditions
    unsupported_conditions: tuple[UnsupportedCondition, ...] = ()


_FIELD_MODEL: dict[SupportedField, type[StrictModel]] = {
    SupportedField.APPLICANT_NAME: ApplicantNameCondition,
    SupportedField.CANDIDATE_POSITION: PositionCondition,
    SupportedField.MINIMUM_DEGREE: DegreeCondition,
    SupportedField.WORK_YEARS: WorkYearsCondition,
    SupportedField.COMPANY: CompanyCondition,
    SupportedField.SCHOOL: SchoolCondition,
    SupportedField.EXPECTED_CITY: LocationCondition,
    SupportedField.CURRENT_CITY: LocationCondition,
    SupportedField.SCHOOL_LEVEL: SchoolLevelCondition,
}


def apply_plan_patch(current: SearchConditions, patch: PlanPatch) -> SearchConditions:
    """应用明确的增量操作，并保留所有未提及条件。"""

    values: dict[str, Any] = current.model_dump(mode="python")
    for operation in patch.operations:
        if operation.operation is PatchOperation.RESET:
            values = {}
            continue

        assert operation.field is not None  # PlanPatchItem 校验已经保证该字段存在。
        key = operation.field.value
        if operation.operation is PatchOperation.REMOVE:
            values[key] = None
            continue

        model_type = _FIELD_MODEL[operation.field]
        normalized_value = _normalize_patch_value(operation.field, operation.value)
        if (
            operation.operation is PatchOperation.ADD
            and operation.field in _LIST_FIELD_KEYS
            and isinstance(values.get(key), dict)
        ):
            # ADD 在列表字段上与现有值合并，模型只需要提供新增的值。
            normalized_value = _merge_add_value(operation.field, values[key], normalized_value)
        values[key] = model_type.model_validate(
            normalized_value, strict=False
        ).model_dump(mode="python")

    return SearchConditions.model_validate(values)


_LIST_FIELD_KEYS = {
    SupportedField.COMPANY: "names",
    SupportedField.SCHOOL: "names",
    SupportedField.SCHOOL_LEVEL: "labels",
}


def _merge_add_value(
    field: SupportedField, existing: dict, incoming: dict
) -> dict:
    """列表字段的 ADD 取并集，未提及的属性保持原值。"""

    list_key = _LIST_FIELD_KEYS[field]
    existing_values = list(existing.get(list_key) or [])
    incoming_values = list(incoming.get(list_key) or [])
    merged = dict(existing)
    merged[list_key] = existing_values + [
        value for value in incoming_values if value not in existing_values
    ]
    if field is SupportedField.SCHOOL_LEVEL:
        # 第一学历限制只要表达过就保留，不能因为追加普通标签而丢失。
        merged["first_degree_only"] = bool(existing.get("first_degree_only")) or bool(
            incoming.get("first_degree_only", False)
        )
    return merged


def _normalize_patch_value(field: SupportedField, value: JsonValue | None) -> JsonValue | None:
    """修正常见的单值列表形状，不改变模型识别出的业务含义。"""

    if not isinstance(value, dict):
        return value
    normalized = dict(value)
    list_field: str | None = None
    aliases: tuple[str, ...] = ()
    if field in {SupportedField.COMPANY, SupportedField.SCHOOL}:
        list_field = "names"
        aliases = ("value", "name")
    elif field is SupportedField.SCHOOL_LEVEL:
        list_field = "labels"
        aliases = ("value", "label")

    if list_field and list_field not in normalized:
        for alias in aliases:
            raw_value = normalized.pop(alias, None)
            if raw_value:
                normalized[list_field] = (
                    raw_value if isinstance(raw_value, list) else [raw_value]
                )
                break
    return normalized
