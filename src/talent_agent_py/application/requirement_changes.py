"""显式应用需求变更，不让遗漏字段删除已有要求。"""

from talent_agent_py.domain.matching import RequirementChange, SearchRequirements
from talent_agent_py.domain.plan import apply_plan_patch


def prefer_non_filter_requirements(requirements: SearchRequirements) -> SearchRequirements:
    """固定筛选之外只做偏好排序，资料缺失不能淘汰候选人。"""

    preferences = []
    seen = set()
    for item in (
        requirements.required_criteria
        + requirements.preferences
        + requirements.interview_items
    ):
        if item.id not in seen:
            preferences.append(item)
            seen.add(item.id)
    return requirements.model_copy(update={
        "required_criteria": [],
        "preferences": preferences,
        "interview_items": [],
    }, deep=True)


def apply_requirement_change(current: SearchRequirements, change: RequirementChange, version: int):
    updated = current.model_copy(deep=True)
    if not change.is_job_request:
        updated.ambiguities = ["请提供职位要求或描述要找的人"]
        return updated
    if change.filters_patch is not None:
        if change.filters_patch.base_plan_version != version:
            raise ValueError("需求版本不一致")
        updated.conditions = apply_plan_patch(current.conditions, change.filters_patch)
    for edit in change.criterion_edits:
        items = list(getattr(updated, edit.group))
        existing = next((i for i, item in enumerate(items) if item.id == edit.criterion_id), None)
        if edit.operation == "ADD":
            if existing is not None:
                raise ValueError("要求已存在，不能重复增加")
            items.append(edit.value)
        else:
            if existing is None:
                raise ValueError("找不到要修改的要求")
            if edit.operation == "REMOVE":
                items.pop(existing)
            else:
                items[existing] = edit.value
        setattr(updated, edit.group, items)
    updated.source_text = (current.source_text + "\n" + change.source_text).strip()[-20000:]
    updated.ambiguities = change.ambiguities
    if change.filters_patch:
        updated.ambiguities += [item.reason for item in change.filters_patch.ambiguities]
        updated.ambiguities += [item.reason for item in change.filters_patch.unsupported_conditions]
    validated = SearchRequirements.model_validate(updated.model_dump())
    return prefer_non_filter_requirements(validated)
