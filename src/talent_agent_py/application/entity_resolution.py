"""将 Java 字典解析结果安全地合并回搜索草稿。"""

from talent_agent_py.application.ports.talent_search import (
    EntityResolution,
    EntityResolutionRequest,
    TalentSearchPort,
)
from talent_agent_py.domain.conversation import UserContext
from talent_agent_py.domain.enums import EntityKind, EntityResolutionStatus
from talent_agent_py.domain.plan import Ambiguity, ResolvedEntity, SearchPlanDraft


def build_resolution_requests(draft: SearchPlanDraft) -> list[EntityResolutionRequest]:
    """只为确实需要业务 code 的五类实体构造请求。"""

    conditions = draft.conditions
    requests: list[EntityResolutionRequest] = []
    if conditions.minimum_degree:
        requests.append(EntityResolutionRequest(
            key="minimum_degree", kind=EntityKind.DEGREE, text=conditions.minimum_degree.value
        ))
    if conditions.company:
        requests.extend(EntityResolutionRequest(
            key=f"company:{index}", kind=EntityKind.COMPANY, text=name
        ) for index, name in enumerate(conditions.company.names))
    if conditions.school:
        requests.extend(EntityResolutionRequest(
            key=f"school:{index}", kind=EntityKind.SCHOOL, text=name
        ) for index, name in enumerate(conditions.school.names))
    for field_name in ("current_city", "expected_city"):
        location = getattr(conditions, field_name)
        if location:
            requests.append(EntityResolutionRequest(
                key=field_name, kind=EntityKind.CITY, text=location.name
            ))
    if conditions.school_level:
        requests.extend(EntityResolutionRequest(
            key=f"school_level:{index}", kind=EntityKind.SCHOOL_LEVEL, text=label
        ) for index, label in enumerate(conditions.school_level.labels))
    return requests


def _single_entity(result: EntityResolution) -> ResolvedEntity | None:
    if result.status is not EntityResolutionStatus.RESOLVED or len(result.candidates) != 1:
        return None
    candidate = result.candidates[0]
    return ResolvedEntity(code=candidate.code, label=candidate.label)


async def resolve_draft_entities(
    draft: SearchPlanDraft,
    port: TalentSearchPort,
    user: UserContext,
) -> SearchPlanDraft:
    """合并唯一结果；多义和未找到都转成必须澄清的问题。"""

    requests = build_resolution_requests(draft)
    if not requests:
        return draft
    results = {item.key: item for item in await port.resolve_entities(requests, user)}
    request_text_by_key = {item.key: item.text for item in requests}
    data = draft.model_dump(mode="python")
    conditions = data["conditions"]
    ambiguities = list(draft.ambiguities)

    # 即使模型伪造了 resolved.code，也必须先清空，再只写入 Java 返回的结果。
    if conditions.get("minimum_degree"):
        conditions["minimum_degree"]["resolved"] = None
    for field_name in ("company", "school", "school_level"):
        if conditions.get(field_name):
            conditions[field_name]["resolved"] = []
    for field_name in ("current_city", "expected_city"):
        if conditions.get(field_name):
            conditions[field_name]["resolved"] = None

    def resolved_for(key: str) -> ResolvedEntity | None:
        result = results.get(key)
        if result is None:
            ambiguities.append(Ambiguity(
                field=key,
                reason="Java 未返回实体解析结果",
                input_text=request_text_by_key.get(key),
            ))
            return None
        entity = _single_entity(result)
        if entity is None:
            ambiguities.append(Ambiguity(
                field=key,
                reason="业务实体无法唯一确定",
                input_text=request_text_by_key.get(key),
                options=[candidate.label for candidate in result.candidates],
                entity_options=[
                    ResolvedEntity(code=candidate.code, label=candidate.label)
                    for candidate in result.candidates
                ],
            ))
        return entity

    if conditions.get("minimum_degree"):
        entity = resolved_for("minimum_degree")
        if entity:
            conditions["minimum_degree"]["resolved"] = entity.model_dump(mode="python")
    for field_name in ("company", "school", "school_level"):
        condition = conditions.get(field_name)
        if not condition:
            continue
        source_values = condition["names"] if field_name != "school_level" else condition["labels"]
        resolved = []
        for index in range(len(source_values)):
            entity = resolved_for(f"{field_name}:{index}")
            if entity:
                resolved.append(entity.model_dump(mode="python"))
        condition["resolved"] = resolved
    for field_name in ("current_city", "expected_city"):
        if conditions.get(field_name):
            entity = resolved_for(field_name)
            if entity:
                conditions[field_name]["resolved"] = entity.model_dump(mode="python")

    data["ambiguities"] = [item.model_dump(mode="python") for item in ambiguities]
    return SearchPlanDraft.model_validate(data)
