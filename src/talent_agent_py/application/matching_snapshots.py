"""集中处理快照版本，旧数据不改写，未知版本不猜测。"""

from talent_agent_py.application.exceptions import TalentAgentError, TalentSearchDeniedError
from talent_agent_py.domain.conversation import UserContext
from talent_agent_py.domain.matching import (
    MatchingDraftSnapshot,
    MatchingPlanSnapshot,
    MatchingReplySnapshot,
    MatchingRunSnapshot,
    OwnerScope,
)
from talent_agent_py.domain.plan import SearchPlan


class SnapshotVersionError(TalentAgentError):
    code = "UNSUPPORTED_SNAPSHOT_VERSION"


def snapshot_kind(payload: dict) -> str | None:
    version = payload.get("schema_version", 1)
    kind = payload.get("kind")
    # V1 澄清卡和消息本来就有 kind，不能把业务类型当作快照版本。
    if version == 1 and not (isinstance(kind, str) and kind.startswith("matching_")):
        return None
    if version != 2 or kind not in {
        "matching_plan", "matching_run", "matching_reply", "matching_draft"
    }:
        raise SnapshotVersionError("该记录版本当前服务无法读取，请使用兼容版本")
    return kind


def read_snapshot(payload: dict):
    models = {
        "matching_plan": MatchingPlanSnapshot,
        "matching_run": MatchingRunSnapshot,
        "matching_reply": MatchingReplySnapshot,
        "matching_draft": MatchingDraftSnapshot,
    }
    kind = snapshot_kind(payload)
    if kind is None:
        raise SnapshotVersionError("此入口需要 V2 快照")
    return models[kind].model_validate(payload, strict=False)


def read_search_plan(payload: dict) -> SearchPlan:
    kind = snapshot_kind(payload)
    if kind is None:
        return SearchPlan.model_validate(payload, strict=False)
    if kind != "matching_plan":
        raise SnapshotVersionError("记录不是搜索计划")
    return MatchingPlanSnapshot.model_validate(payload, strict=False).search_plan


def owner_scope(session_id: str, user: UserContext) -> OwnerScope:
    return OwnerScope(session_id=session_id, user_id=user.user_id, tenant_id=user.tenant_id)


def check_owner(scope: OwnerScope, session_id: str, user: UserContext) -> None:
    if scope != owner_scope(session_id, user):
        raise TalentSearchDeniedError("无权访问该匹配记录")
