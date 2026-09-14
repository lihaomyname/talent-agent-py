"""SearchPlan 领域规则测试。"""

import pytest
from pydantic import ValidationError

from talent_agent_py.domain.enums import LocationScope, PatchOperation, SupportedField
from talent_agent_py.domain.plan import (
    ApplicantNameCondition,
    CompanyCondition,
    LocationCondition,
    PlanPatch,
    PlanPatchItem,
    SearchConditions,
    WorkYearsCondition,
    apply_plan_patch,
)


def test_work_years_rejects_reverse_range():
    with pytest.raises(ValidationError):
        WorkYearsCondition(minimum=5, maximum=3)


def test_plan_patch_preserves_unmentioned_conditions():
    current = SearchConditions(
        applicant_name=ApplicantNameCondition(value="张三"),
        current_city=LocationCondition(name="杭州", scope=LocationScope.CURRENT_CITY),
        work_years=WorkYearsCondition(minimum=3),
    )
    patch = PlanPatch(
        base_plan_version=1,
        operations=[PlanPatchItem(
            operation=PatchOperation.REPLACE,
            field=SupportedField.CURRENT_CITY,
            value={"name": "上海", "scope": "CURRENT_CITY", "resolved": None},
        )],
    )

    updated = apply_plan_patch(current, patch)

    assert updated.applicant_name.value == "张三"
    assert updated.work_years.minimum == 3
    assert updated.current_city.name == "上海"


def test_strict_models_reject_unknown_fields():
    with pytest.raises(ValidationError):
        ApplicantNameCondition(value="张三", operator_id="forbidden")


def test_reset_clears_all_previous_conditions():
    current = SearchConditions(applicant_name=ApplicantNameCondition(value="张三"))
    patch = PlanPatch(
        base_plan_version=1,
        operations=[PlanPatchItem(operation=PatchOperation.RESET)],
    )
    assert apply_plan_patch(current, patch) == SearchConditions()


def test_company_patch_accepts_model_single_value_shape():
    """模型把单个公司写成 value 时，应归一化为 names 数组。"""

    patch = PlanPatch(
        base_plan_version=1,
        operations=[PlanPatchItem(
            operation=PatchOperation.ADD,
            field=SupportedField.COMPANY,
            value={"value": "阿里巴巴", "scope": "CURRENT_OR_HISTORY"},
        )],
    )

    updated = apply_plan_patch(SearchConditions(), patch)

    assert updated.company == CompanyCondition(names=["阿里巴巴"])
