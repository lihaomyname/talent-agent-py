"""复用现有表的匹配读写。事务由调用方管理，不持有外部调用。"""

import json

from sqlalchemy import select

from talent_agent_py.application.exceptions import SessionNotFoundError, StalePageReferenceError
from talent_agent_py.application.matching_snapshots import check_owner, read_snapshot, snapshot_kind
from talent_agent_py.domain.matching import (
    MatchingPlanSnapshot,
    MatchingRunSnapshot,
    SearchRequirements,
)
from talent_agent_py.infrastructure.persistence.models import RunRecord, SearchPlanRecord


class SnapshotCapacityError(ValueError):
    """快照容量到限，不应当被当作外部依赖错误。"""


async def owned_session(uow, session_id, user):
    session = await uow.sessions.get_owned(session_id, user.user_id)
    if session is None:
        raise SessionNotFoundError("会话不存在")
    # 新计划绑定租户；避免纯 V1 入口绕过 V2 作用域。
    record = await uow.session.scalar(select(SearchPlanRecord).where(
        SearchPlanRecord.session_id == session_id
    ).order_by(SearchPlanRecord.version.desc()).limit(1))
    if record and snapshot_kind(record.plan_json):
        check_owner(read_snapshot(record.plan_json).owner_scope, session_id, user)
    return session


async def current_requirements(uow, session_id, user):
    session = await owned_session(uow, session_id, user)
    record = await uow.session.scalar(select(SearchPlanRecord).where(
        SearchPlanRecord.session_id == session_id
    ).order_by(SearchPlanRecord.version.desc()).limit(1))
    if record is None:
        return session, SearchRequirements(), 0
    if snapshot_kind(record.plan_json) == "matching_plan":
        snapshot = MatchingPlanSnapshot.model_validate(record.plan_json, strict=False)
        return session, snapshot.requirements, record.version
    plan = await uow.plans.get_current(session_id)
    return session, SearchRequirements(conditions=plan.conditions), plan.version


async def load_run(uow, session_id, run_id, user):
    await owned_session(uow, session_id, user)
    run = await uow.runs.get(run_id)
    if run is None or run.session_id != session_id or not run.result_json:
        raise SessionNotFoundError("匹配运行不存在")
    snapshot = read_snapshot(run.result_json)
    if not isinstance(snapshot, MatchingRunSnapshot):
        raise StalePageReferenceError("该运行不是匹配任务")
    check_owner(snapshot.owner_scope, session_id, user)
    record = await uow.session.scalar(select(SearchPlanRecord).where(
        SearchPlanRecord.session_id == session_id,
        SearchPlanRecord.version == snapshot.plan_version,
    ))
    if record is None:
        raise SessionNotFoundError("匹配需求版本不存在")
    plan = MatchingPlanSnapshot.model_validate(record.plan_json, strict=False)
    check_owner(plan.owner_scope, session_id, user)
    return run, snapshot, plan


def encode_run(snapshot, maximum_bytes):
    data = snapshot.model_dump(mode="json")
    if len(json.dumps(data, ensure_ascii=False).encode()) > maximum_bytes:
        raise SnapshotCapacityError("匹配快照超过容量限制")
    return data


async def recover_interrupted(uow):
    records = (await uow.session.scalars(select(RunRecord).where(
        RunRecord.status.in_(["QUEUED", "RUNNING"])
    ))).all()
    for record in records:
        if not record.result_json or snapshot_kind(record.result_json) != "matching_run":
            continue
        snapshot = MatchingRunSnapshot.model_validate(record.result_json, strict=False)
        snapshot.stop_reason = "INTERRUPTED"
        record.result_json = snapshot.model_dump(mode="json")
        record.status = "FAILED"
        record.stage = "interrupted"
        record.error_code = "PROCESS_RESTARTED"
