"""验证用户和模型不能扩大 Java 搜索权限。"""

import pytest
from pydantic import SecretStr, ValidationError

from talent_agent_py.application.entity_resolution import resolve_draft_entities
from talent_agent_py.application.ports.talent_search import (
    EntityCandidate,
    EntityResolution,
    TalentSearchRequest,
)
from talent_agent_py.domain.conversation import UserContext
from talent_agent_py.domain.enums import EntityKind, EntityResolutionStatus
from talent_agent_py.domain.plan import (
    DegreeCondition,
    ResolvedEntity,
    SearchConditions,
    SearchPlanDraft,
)


def test_java_request_rejects_operator_and_unmask_fields():
    with pytest.raises(ValidationError):
        TalentSearchRequest(
            operatorId="attacker",
            hideClue=False,
        )


def test_java_request_rejects_excessive_page_size():
    with pytest.raises(ValidationError):
        TalentSearchRequest(pageSize=11)


async def test_model_supplied_business_code_is_replaced_by_java():
    class Resolver:
        async def resolve_entities(self, requests, user):
            return [EntityResolution(
                key="minimum_degree",
                kind=EntityKind.DEGREE,
                status=EntityResolutionStatus.RESOLVED,
                candidates=[EntityCandidate(code="06", label="本科")],
            )]

    draft = SearchPlanDraft(conditions=SearchConditions(
        minimum_degree=DegreeCondition(
            value="本科",
            resolved=ResolvedEntity(code="forged", label="伪造值"),
        )
    ))
    resolved = await resolve_draft_entities(draft, Resolver(), UserContext(user_id="u1"))
    assert resolved.conditions.minimum_degree.resolved.code == "06"


def test_request_cookie_is_excluded_from_serialization_and_repr():
    """临时登录令牌不能进入图检查点、日志字段或数据库 JSON。"""

    context = UserContext(
        user_id="u1",
        auth_open_id_token=SecretStr("sensitive-cookie"),
    )
    assert "auth_open_id_token" not in context.model_dump()
    assert "sensitive-cookie" not in repr(context)
