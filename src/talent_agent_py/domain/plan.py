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

    # 招聘系统返回的业务编码，不能由模型自行编造。
    code: str = Field(min_length=1, max_length=128)
    # 供用户阅读的实体或选项名称。
    label: str = Field(min_length=1, max_length=200)


class ApplicantNameCondition(StrictModel):
    """候选人姓名条件。"""

    # 用户要求搜索的候选人姓名。
    value: str = Field(min_length=1, max_length=100)
    # 姓名匹配方式，默认精确匹配。
    match_mode: NameMatchMode = NameMatchMode.EXACT


class PositionCondition(StrictModel):
    """候选人简历职位，与招聘职位 ID 无关。"""

    # 候选人简历中的职位名称，不是招聘职位 ID。
    value: str = Field(min_length=1, max_length=200)
    # 职位经历范围：仅当前，或当前及历史。
    scope: ExperienceScope = ExperienceScope.CURRENT_OR_HISTORY


class DegreeCondition(StrictModel):
    """最低学历语义值，以及可选的 Java 解析结果。"""

    # 用户表达的最低学历名称，实体解析后才能取得业务编码。
    value: str = Field(min_length=1, max_length=50)
    # 招聘系统解析后的实体；尚未解析时为空。
    resolved: ResolvedEntity | None = None


class WorkYearsCondition(StrictModel):
    """面向招聘人员表达的总工作年限范围。"""

    # 总工作年限下限，单位年；为空表示未限制下限。
    minimum: int | None = Field(default=None, ge=0, le=60)
    # 总工作年限上限，单位年；为空表示未限制上限。
    maximum: int | None = Field(default=None, ge=0, le=60)

    @model_validator(mode="after")
    def validate_range(self) -> WorkYearsCondition:
        """校验至少有一个年限边界且下限不大于上限，通过后返回自身。"""

        if self.minimum is None and self.maximum is None:
            raise ValueError("work years requires a minimum or maximum")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("work years minimum cannot exceed maximum")
        return self


class CompanyCondition(StrictModel):
    """共享当前/历史范围的一组公司。"""

    # 用户要求匹配的公司名称列表。
    names: list[str] = Field(min_length=1, max_length=20)
    # 整组公司共享的经历范围：仅当前，或当前及历史。
    scope: ExperienceScope = ExperienceScope.CURRENT_OR_HISTORY
    # 招聘系统解析后的实体；尚未解析时为空。
    resolved: list[ResolvedEntity] = Field(default_factory=list, max_length=20)


class SchoolCondition(StrictModel):
    """由 Java 解析的一组学校。"""

    # 用户要求匹配的毕业院校名称列表。
    names: list[str] = Field(min_length=1, max_length=20)
    # 招聘系统解析后的实体；尚未解析时为空。
    resolved: list[ResolvedEntity] = Field(default_factory=list, max_length=20)


class LocationCondition(StrictModel):
    """一个城市及其现居/期望语义。"""

    # 用户表达的城市名称，待招聘系统解析。
    name: str = Field(min_length=1, max_length=100)
    # 城市语义：现居住地或期望工作地。
    scope: LocationScope
    # 招聘系统解析后的实体；尚未解析时为空。
    resolved: ResolvedEntity | None = None


class SchoolLevelCondition(StrictModel):
    """院校等级标签和第一学历限制。"""

    # 院校等级标签，如 985、211。
    labels: list[str] = Field(min_length=1, max_length=20)
    # 是否将院校标签限制到第一学历。
    first_degree_only: bool = False
    # 招聘系统解析后的实体；尚未解析时为空。
    resolved: list[ResolvedEntity] = Field(default_factory=list, max_length=20)


class SearchConditions(StrictModel):
    """V1 可执行条件的完整集合。"""

    # 姓名条件；为空表示不限制。
    applicant_name: ApplicantNameCondition | None = None
    # 候选人职位条件；为空表示不限制。
    candidate_position: PositionCondition | None = None
    # 最低学历条件；为空表示不限制。
    minimum_degree: DegreeCondition | None = None
    # 总工作年限范围；为空表示不限制。
    work_years: WorkYearsCondition | None = None
    # 公司经历条件；为空表示不限制。
    company: CompanyCondition | None = None
    # 毕业院校条件；为空表示不限制。
    school: SchoolCondition | None = None
    # 期望工作地条件；为空表示不限制。
    expected_city: LocationCondition | None = None
    # 现居住地条件；为空表示不限制。
    current_city: LocationCondition | None = None
    # 院校等级条件；为空表示不限制。
    school_level: SchoolLevelCondition | None = None

    @model_validator(mode="after")
    def validate_location_scopes(self) -> SearchConditions:
        """校验城市字段和城市范围一致，通过后返回自身。"""

        if self.current_city and self.current_city.scope is not LocationScope.CURRENT_CITY:
            raise ValueError("current_city must use CURRENT_CITY scope")
        if self.expected_city and self.expected_city.scope is not LocationScope.EXPECTED_CITY:
            raise ValueError("expected_city must use EXPECTED_CITY scope")
        return self


class UnsupportedCondition(StrictModel):
    """模型能够理解、但 V1 无法执行的用户条件。"""

    # 用户原始条件文本，供澄清时展示。
    original_text: str = Field(min_length=1, max_length=500)
    # 当前版本无法执行该条件的原因。
    reason: str = Field(min_length=1, max_length=500)
    # 是否为用户硬要求；当前校验仍会阻塞所有未处理的不支持条件。
    hard_requirement: bool = True


class Ambiguity(StrictModel):
    """搜索前发现的阻塞性语义选择。"""

    # 需要澄清的字段路径，可包含列表下标。
    field: str = Field(min_length=1, max_length=100)
    # 无法直接执行的原因。
    reason: str = Field(min_length=1, max_length=500)
    # 语义层可选文本，例如本科、硕士、博士。
    options: list[str] = Field(default_factory=list, max_length=20)
    # 招聘系统提供的实体候选，包含可用于回填的编码。
    entity_options: list[ResolvedEntity] = Field(default_factory=list, max_length=20)
    # 需要重新描述或忽略的原始实体文本；未知时为空。
    input_text: str | None = Field(default=None, min_length=1, max_length=200)


class Preference(StrictModel):
    """不参与招聘接口过滤、只用于简历证据匹配的一项偏好。"""

    id: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=500)
    source_quote: str = Field(min_length=1, max_length=500)


class SearchPlanDraft(StrictModel):
    """Java 实体解析前的语义草稿。"""

    # 数据结构版本，供结构化输出及持久化快照识别。
    schema_version: int = 1
    # 本轮使用的九类受支持搜索条件。
    conditions: SearchConditions = Field(default_factory=SearchConditions)
    # “最好、优先、加分”等软要求；不阻塞搜索，也不转换成硬筛选条件。
    preferences: list[Preference] = Field(default_factory=list, max_length=20)
    # 城市已识别但现居或期望范围未知时保存的名称。
    unresolved_location: str | None = Field(default=None, min_length=1, max_length=100)
    # 无法由当前搜索接口执行的条件，保留供用户澄清。
    unsupported_conditions: list[UnsupportedCondition] = Field(default_factory=list)
    # 阻塞执行的歧义，需用户回答后才能继续。
    ambiguities: list[Ambiguity] = Field(default_factory=list)


class PlanPatchItem(StrictModel):
    """后续用户轮次请求的一项计划修改。"""

    # 增加、替换、删除或清空操作。
    operation: PatchOperation
    # 操作目标字段；RESET 时必须为空。
    field: SupportedField | None = None
    # 操作载荷，实际结构由 field 对应的条件模型校验。
    value: JsonValue | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> PlanPatchItem:
        """校验补丁操作的必需字段，避免 RESET 携带目标或 ADD 缺失载荷。"""

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

    # 数据结构版本，供结构化输出及持久化快照识别。
    schema_version: int = 1
    # 补丁基于的计划版本，应用前必须与当前版本一致。
    base_plan_version: int = Field(ge=0)
    # 按顺序应用的修改指令；只有澄清或不支持条件时为空。
    operations: list[PlanPatchItem] = Field(max_length=30)
    # None 表示保持原偏好；空列表表示清空；非空列表表示用完整列表替换。
    preferences: list[Preference] | None = Field(default=None, max_length=20)
    # 无法由当前搜索接口执行的条件，保留供用户澄清。
    unsupported_conditions: list[UnsupportedCondition] = Field(default_factory=list)
    # 阻塞执行的歧义，需用户回答后才能继续。
    ambiguities: list[Ambiguity] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_nonempty_patch(self) -> PlanPatch:
        """允许先澄清，但拒绝没有操作也没有任何待处理条件的补丁。"""

        if not (
            self.operations
            or self.preferences is not None
            or self.unsupported_conditions
            or self.ambiguities
        ):
            raise ValueError(
                "plan patch requires operations, preferences, unsupported conditions or ambiguities"
            )
        return self


class SearchPlan(StrictModel):
    """不可变、可执行且可审计的搜索计划。"""

    model_config = StrictModel.model_config | {"frozen": True}

    # 数据结构版本，供结构化输出及持久化快照识别。
    schema_version: int = 1
    # 当前会话内从 1 递增的计划版本。
    version: int = Field(ge=1)
    # 此计划已吸收的最后消息序号，下一轮从其后继续读取。
    applied_through_message_seq: int = Field(ge=0)
    # 本轮使用的九类受支持搜索条件。
    conditions: SearchConditions
    # 偏好与固定条件属于同一个计划，但不会编译到 Java 搜索请求中。
    preferences: tuple[Preference, ...] = ()
    # 无法由当前搜索接口执行的条件，保留供用户澄清。
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
        values[key] = model_type.model_validate(normalized_value, strict=False).model_dump(
            mode="python"
        )

    return SearchConditions.model_validate(values)


_LIST_FIELD_KEYS = {
    SupportedField.COMPANY: "names",
    SupportedField.SCHOOL: "names",
    SupportedField.SCHOOL_LEVEL: "labels",
}


def _merge_add_value(
    field: SupportedField, existing: dict[str, Any], incoming: dict[str, Any]
) -> dict[str, Any]:
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
                normalized[list_field] = raw_value if isinstance(raw_value, list) else [raw_value]
                break
    return normalized
