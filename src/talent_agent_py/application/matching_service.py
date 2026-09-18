"""匹配应用入口：确认需求、持久化运行、有限检索及授权读取。"""

import asyncio
import time

from sqlalchemy import select

from talent_agent_py.application.candidate_profiles import (
    evaluation_rank,
    failed_evaluation,
    validate_evaluation,
)
from talent_agent_py.application.entity_resolution import resolve_draft_entities
from talent_agent_py.application.exceptions import (
    FeatureDisabledError,
    ModelOutputError,
    StalePageReferenceError,
    TalentSearchDeniedError,
    TalentSearchDependencyError,
)
from talent_agent_py.application.matching_snapshots import check_owner, owner_scope, read_snapshot
from talent_agent_py.application.matching_store import (
    SnapshotCapacityError,
    current_requirements,
    encode_run,
    load_run,
    owned_session,
    recover_interrupted,
)
from talent_agent_py.application.plan_validation import validate_draft
from talent_agent_py.application.requirement_changes import (
    apply_requirement_change,
    prefer_non_filter_requirements,
)
from talent_agent_py.application.search_compiler import compile_search_request
from talent_agent_py.domain.conversation import MessageOutcome, PageReference, SearchResult
from talent_agent_py.domain.enums import ResultStatus
from talent_agent_py.domain.matching import (
    MatchingBudget,
    MatchingDraftSnapshot,
    MatchingPlanSnapshot,
    MatchingReplySnapshot,
    MatchingRunSnapshot,
    SearchRequirements,
)
from talent_agent_py.domain.plan import SearchPlan, SearchPlanDraft
from talent_agent_py.infrastructure.persistence.models import (
    PendingClarificationRecord,
    SearchPlanRecord,
)
from talent_agent_py.infrastructure.persistence.repositories import new_id
from talent_agent_py.orchestration.interruptible import complete_before_cancel


class MatchingService:
    def __init__(self, *, uow_factory, llm, talent_search, tasks, settings, message_lock):
        self.uow_factory = uow_factory
        self.llm = llm
        self.talent = talent_search
        self.tasks = tasks
        self.settings = settings
        self.message_lock = message_lock
        self.input_slots = asyncio.Semaphore(settings.matching_max_input_calls)

    def require_enabled(self):
        if not self.settings.enable_matching:
            raise FeatureDisabledError("多模态匹配尚未开启")

    async def recover(self):
        async with self.uow_factory() as uow:
            await recover_interrupted(uow)

    async def extract_image_requirement(self, content: str, image: bytes) -> str:
        """把截图和补充文字整理成自然语言需求，后续复用普通消息入口。"""

        self.require_enabled()
        instruction = content.strip() or "请完整提取截图中的职位要求"
        async with self.input_slots:
            change = await self.llm.extract(instruction, SearchRequirements(), 0, image)
        extracted = change.source_text.strip()
        if content.strip() and content.strip() not in extracted:
            return f"{extracted}\n补充要求：{content.strip()}" if extracted else content.strip()
        return extracted or instruction

    async def prepare(self, session_id, user, content, request_key, image=None):
        self.require_enabled()
        async with self.uow_factory() as uow:
            _, current, version = await current_requirements(uow, session_id, user)
            duplicate = await uow.messages.get_by_client_id(session_id, request_key)
            if duplicate:
                pending = await uow.session.scalar(select(PendingClarificationRecord).where(
                    PendingClarificationRecord.session_id == session_id,
                ))
                if pending and pending.source_message_sequence == duplicate.sequence:
                    saved = read_snapshot(pending.draft_json)
                    check_owner(saved.owner_scope, session_id, user)
                    return saved
                raise StalePageReferenceError("这条输入已处理，请查看历史")
            # 继续编辑尚未确认的卡片时，以该草稿为基准，不能丢失截图内容。
            pending = await uow.session.scalar(select(PendingClarificationRecord).where(
                PendingClarificationRecord.session_id == session_id,
            ))
            if pending and pending.draft_json and pending.draft_json.get("kind") == "matching_draft":
                saved = read_snapshot(pending.draft_json)
                check_owner(saved.owner_scope, session_id, user)
                if saved.base_plan_version == version:
                    current = saved.requirements
            if any(marker in content for marker in ("清空条件", "重新找", "重新搜索", "从头开始")):
                current = SearchRequirements()
        async with self.input_slots:
            change = None
            for attempt in range(2):
                try:
                    change = await self.llm.extract(content, current, version, image)
                    requirements = apply_requirement_change(current, change, version)
                    break
                except (ModelOutputError, ValueError):
                    if attempt == 1:
                        raise
        async with self.message_lock:
            async with self.uow_factory() as uow:
                _, _, latest = await current_requirements(uow, session_id, user)
                if latest != version:
                    raise StalePageReferenceError("解析期间需求已经更新，请重新提交")
                saved_message = content.strip()
                if image:
                    if saved_message:
                        saved_message = "[职位截图]\n" + saved_message
                    else:
                        saved_message = "[职位截图]"
                message, created = await uow.messages.append_user(
                    session_id, request_key, saved_message,
                )
                existing = await uow.session.scalar(select(PendingClarificationRecord).where(
                    PendingClarificationRecord.session_id == session_id,
                ))
                if not created:
                    if existing and existing.source_message_sequence == message.sequence:
                        return read_snapshot(existing.draft_json)
                    raise StalePageReferenceError("这条输入已经处理，请查看会话历史")
                draft = MatchingDraftSnapshot(
                    owner_scope=owner_scope(session_id, user), requirements=requirements,
                    base_plan_version=version, requirement_id=new_id("req"),
                    source_message_sequence=message.sequence, input_type="image" if image else "text",
                )
                message.route_type = "MATCHING_INPUT"
                message.outcome_json = MatchingReplySnapshot(
                    owner_scope=draft.owner_scope, requirement_id=draft.requirement_id,
                ).model_dump(mode="json")
                if existing:
                    existing.question_id = draft.requirement_id
                    existing.source_message_sequence = message.sequence
                    existing.card_json = {"schema_version": 2, "kind": "matching_draft"}
                    existing.draft_json = draft.model_dump(mode="json")
                else:
                    uow.session.add(PendingClarificationRecord(
                        question_id=draft.requirement_id, session_id=session_id,
                        source_message_sequence=message.sequence,
                        card_json={"schema_version": 2, "kind": "matching_draft"},
                        draft_json=draft.model_dump(mode="json"),
                    ))
                return draft

    async def confirm(self, session_id, user, requirement_id, request_key, requirements):
        self.require_enabled()
        requirements = prefer_non_filter_requirements(requirements)
        # 在任何外部请求或取消动作之前验证归属、幂等和草稿。
        async with self.uow_factory() as uow:
            _, _, version = await current_requirements(uow, session_id, user)
            duplicate = await uow.messages.get_by_client_id(session_id, request_key)
            if duplicate:
                existing_run = await uow.runs.get_by_trigger(session_id, duplicate.sequence)
                if existing_run:
                    return {"run_id": existing_run.id, "mode": "MATCHING" if
                            existing_run.result_json and existing_run.result_json.get("kind") == "matching_run"
                            else "SIMPLE"}
                raise StalePageReferenceError("请求标识已用于其他消息")
            pending = await uow.session.get(PendingClarificationRecord, requirement_id)
            if pending is None or pending.session_id != session_id:
                raise StalePageReferenceError("确认草稿已失效")
            saved = read_snapshot(pending.draft_json)
            check_owner(saved.owner_scope, session_id, user)
            if saved.base_plan_version != version:
                raise StalePageReferenceError("基础需求版本已变化")
        # 实体解析只做网络调用，不持有数据库事务。
        draft = SearchPlanDraft(conditions=requirements.conditions)
        if requirements.ambiguities:
            raise StalePageReferenceError("请先解决待确认项")
        if not validate_draft(draft).executable:
            raise StalePageReferenceError("请提供至少一个可执行搜索条件")
        resolved = await resolve_draft_entities(draft, self.talent, user)
        if not validate_draft(resolved).executable:
            raise StalePageReferenceError("搜索条件实体存在歧义，请修改后确认")
        requirements = requirements.model_copy(update={"conditions": resolved.conditions}, deep=True)
        async with self.message_lock:
            if not await self.tasks.has_capacity(session_id, self.settings.matching_max_active_tasks):
                raise FeatureDisabledError("当前运行任务已达上限，请稍后重试")
            # 预检通过才取消，幂等重试和失效卡片不会打断当前任务。
            async with self.uow_factory() as uow:
                _, _, latest_version = await current_requirements(uow, session_id, user)
                duplicate = await uow.messages.get_by_client_id(session_id, request_key)
                if duplicate:
                    existing = await uow.runs.get_by_trigger(session_id, duplicate.sequence)
                    if existing:
                        return {"run_id": existing.id, "mode": "MATCHING" if requirements.needs_matching() else "SIMPLE"}
                    raise StalePageReferenceError("请求标识已用于其他消息")
                pending = await uow.session.get(PendingClarificationRecord, requirement_id)
                if pending is None or latest_version != version:
                    raise StalePageReferenceError("确认草稿已失效")
            await self.tasks.cancel_and_wait(session_id)
            async with self.uow_factory() as uow:
                session, _, version = await current_requirements(uow, session_id, user)
                message = await uow.messages.get_by_client_id(session_id, request_key)
                if message:
                    run = await uow.runs.get_by_trigger(session_id, message.sequence)
                    if run:
                        return {"run_id": run.id, "mode": "MATCHING"}
                pending = await uow.session.scalar(select(PendingClarificationRecord).where(
                    PendingClarificationRecord.session_id == session_id,
                ))
                if not pending or pending.question_id != requirement_id:
                    raise StalePageReferenceError("确认草稿已失效")
                saved = read_snapshot(pending.draft_json)
                check_owner(saved.owner_scope, session_id, user)
                if saved.base_plan_version != version:
                    raise StalePageReferenceError("基础需求版本已变化")
                message, _ = await uow.messages.append_user(session_id, request_key, "确认搜索需求")
                message.route_type = "MATCHING_CONFIRM"
                plan = SearchPlan(version=version + 1, applied_through_message_seq=message.sequence,
                                  conditions=requirements.conditions)
                snapshot = MatchingPlanSnapshot(owner_scope=saved.owner_scope,
                                                requirements=requirements, search_plan=plan)
                uow.session.add(SearchPlanRecord(
                    id=new_id("plan"), session_id=session_id, version=plan.version,
                    applied_through_message_seq=message.sequence, plan_json=snapshot.model_dump(mode="json"),
                ))
                session.current_plan_version = plan.version
                old_run_id = session.active_run_id
                run = await uow.runs.create(session, message.sequence)
                if old_run_id:
                    await uow.runs.mark_superseded(old_run_id, run.id)
                run.result_json = self._new_snapshot(snapshot, run.id, request_key).model_dump(mode="json")
                message.outcome_json = MatchingReplySnapshot(
                    owner_scope=saved.owner_scope, run_id=run.id, plan_version=plan.version,
                ).model_dump(mode="json")
                await uow.session.delete(pending)
            if requirements.needs_matching():
                await self.tasks.start_replacement(session_id, lambda: self.execute(session_id, run.id, user))
            else:
                await self.tasks.start_replacement(session_id, lambda: self.execute_simple(session_id, run.id, user))
        return {"run_id": run.id, "mode": "MATCHING" if requirements.needs_matching() else "SIMPLE"}

    async def execute_simple(self, session_id, run_id, user):
        """已确认的结构直接搜索，不再次解析，也不调用匹配模型。"""
        async with self.uow_factory() as uow:
            _, snapshot, plan = await load_run(uow, session_id, run_id, user)
        try:
            response = await self.talent.search_candidates(
                compile_search_request(plan.search_plan, self.settings, page=1), user,
            )
            result = SearchResult(
                status=ResultStatus.OK if response.candidates else ResultStatus.EMPTY,
                run_id=run_id, plan_version=snapshot.plan_version,
                candidates=response.candidates, total=response.total,
                executed_conditions=plan.search_plan.conditions,
                next_page=PageReference(session_id=session_id, plan_version=snapshot.plan_version, page=2)
                if response.has_next else None,
            )
            async with self.uow_factory() as uow:
                run = await uow.runs.get(run_id)
                if run.status in {"SUPERSEDED", "CANCELLED"}:
                    return
                run.result_json = result.model_dump(mode="json")
                run.status = "SUCCEEDED"
                run.result_status = result.status.value
                run.stage = "completed"
                message = await uow.messages.get_by_client_id(session_id, snapshot.request_key)
                message.outcome_json = MessageOutcome(kind="RESULT", result=result).model_dump(mode="json")
        except asyncio.CancelledError:
            snapshot.stop_reason = "CANCELLED"
            await self.save(run_id, snapshot, status="CANCELLED", stage="completed")
        except Exception:
            snapshot.stop_reason = "DEPENDENCY_ERROR"
            await self.save(run_id, snapshot, status="FAILED", stage="completed", error="DEPENDENCY_ERROR")

    def _new_snapshot(self, plan, run_id, request_key):
        s = self.settings
        return MatchingRunSnapshot(
            owner_scope=plan.owner_scope, plan_version=plan.search_plan.version,
            continuation_root_run_id=run_id, request_key=request_key,
            budget=MatchingBudget(target=s.matching_target, max_pages=s.matching_max_pages,
                max_candidates=s.matching_max_candidates, max_model_attempts=s.matching_max_model_attempts,
                batch_size=s.matching_batch_size, deadline_seconds=s.matching_deadline_seconds),
        )

    @complete_before_cancel
    async def save(self, run_id, snapshot, *, status="RUNNING", stage="matching", error=None):
        # 给停止原因、结果 ID 和耗时预留空间，容量停止也能写回终态。
        limit = self.settings.matching_max_snapshot_bytes
        if status == "RUNNING":
            limit = max(1, limit - 8192)
        data = encode_run(snapshot, limit)
        async with self.uow_factory() as uow:
            run = await uow.runs.get(run_id)
            if run is None:
                return
            if run.status in {"SUPERSEDED", "CANCELLED"}:
                snapshot.stop_reason = run.status
                data = encode_run(snapshot, self.settings.matching_max_snapshot_bytes)
                status = run.status
            run.result_json = data
            run.status = status
            run.stage = stage
            run.error_code = error
            if status in {"SUCCEEDED", "FAILED", "CANCELLED", "SUPERSEDED"}:
                run.result_status = "OK" if snapshot.output_group else "EMPTY"

    def choose(self, snapshot, requirements):
        cp = snapshot.checkpoint
        eligible, pending = [], []
        for cid in cp.checked_ids:
            if cid in cp.displayed_ids or cid not in cp.profiles:
                continue
            evaluation = cp.evaluations[cid]
            rank = evaluation_rank(evaluation, requirements)
            if rank[0]:
                eligible.append((cid, rank[2], rank[3]))
            elif rank[1] or evaluation.failed:
                pending.append(cid)
        eligible.sort(key=lambda item: (-item[1], -item[2]))
        return [item[0] for item in eligible[:snapshot.budget.target]], pending[:10]

    async def execute(self, session_id, run_id, user):
        async with self.uow_factory() as uow:
            _, snapshot, plan = await load_run(uow, session_id, run_id, user)
        plan = plan.model_copy(update={
            "requirements": prefer_non_filter_requirements(plan.requirements),
        }, deep=True)
        started = time.monotonic()
        status, error = "SUCCEEDED", None
        try:
            async with asyncio.timeout(snapshot.budget.deadline_seconds):
                await self._loop(run_id, snapshot, plan, user)
        except TimeoutError:
            snapshot.stop_reason = "TIME_LIMIT"
        except asyncio.CancelledError:
            snapshot.stop_reason = "CANCELLED"
            status = "CANCELLED"
        except TalentSearchDeniedError:
            snapshot.stop_reason, status, error = "DENIED", "FAILED", "DENIED"
        except SnapshotCapacityError:
            # 恢复最后已提交的小批，不让超大内存状态覆盖可继续的进度。
            async with self.uow_factory() as uow:
                _, snapshot, plan = await load_run(uow, session_id, run_id, user)
            snapshot.stop_reason = "CONTEXT_LIMIT"
        except (TalentSearchDependencyError, ModelOutputError):
            snapshot.stop_reason, status, error = "DEPENDENCY_ERROR", "FAILED", "DEPENDENCY_ERROR"
        except Exception:
            snapshot.stop_reason, status, error = "DEPENDENCY_ERROR", "FAILED", "INTERNAL_ERROR"
        snapshot.usage.elapsed_seconds = round(time.monotonic() - started, 3)
        snapshot.output_group, snapshot.pending_group = self.choose(snapshot, plan.requirements)
        if snapshot.stop_reason in {"DENIED", "SUPERSEDED"}:
            snapshot.output_group, snapshot.pending_group = [], []
        snapshot.checkpoint.displayed_ids += snapshot.output_group + snapshot.pending_group
        await self.save(run_id, snapshot, status=status, stage="completed", error=error)

    async def _loop(self, run_id, snapshot, plan, user):
        cp, usage, budget = snapshot.checkpoint, snapshot.usage, snapshot.budget
        while True:
            chosen, _ = self.choose(snapshot, plan.requirements)
            if len(chosen) >= budget.target:
                snapshot.stop_reason = "TARGET_REACHED"
                return
            if usage.checked_candidates >= budget.max_candidates:
                snapshot.stop_reason = "CANDIDATE_LIMIT"
                return
            if len(cp.checked_ids) >= self.settings.matching_max_total_candidates:
                snapshot.stop_reason = "CONTEXT_LIMIT"
                return
            if not cp.buffered:
                if cp.source_exhausted:
                    snapshot.stop_reason = "SOURCE_EXHAUSTED"
                    return
                if usage.search_calls >= budget.max_pages:
                    snapshot.stop_reason = "PAGE_LIMIT"
                    return
                usage.search_calls += 1
                await self.save(run_id, snapshot)
                request = compile_search_request(plan.search_plan, self.settings, page=cp.next_page)
                page = await self.talent.search_candidate_profiles(request, user)
                # 同页也可能重复，不能仅与历史 ID 去重。
                seen = set(cp.checked_ids)
                cp.buffered = []
                for profile in page.candidates:
                    if profile.candidate_id not in seen:
                        cp.buffered.append(profile)
                        seen.add(profile.candidate_id)
                cp.next_page += 1
                cp.source_exhausted = not page.has_next
                await self.save(run_id, snapshot)
                if not cp.buffered:
                    snapshot.stop_reason = "NO_NEW_CANDIDATES"
                    return
            count = min(
                budget.batch_size,
                budget.max_candidates - usage.checked_candidates,
                self.settings.matching_max_total_candidates - len(cp.checked_ids),
                len(cp.buffered),
            )
            profiles = cp.buffered[:count]
            evaluations = None
            for attempt in range(2):
                if usage.model_attempts >= budget.max_model_attempts:
                    snapshot.stop_reason = "MODEL_LIMIT"
                    return
                usage.model_attempts += 1
                await self.save(run_id, snapshot)
                try:
                    batch = await self.llm.evaluate(plan.requirements, profiles)
                    by_id = {item.candidate_id: item for item in batch.evaluations}
                    if len(by_id) != len(profiles) or len(batch.evaluations) != len(profiles):
                        raise ValueError("批次人选数量不一致")
                    for profile in profiles:
                        validate_evaluation(by_id[profile.candidate_id], profile, plan.requirements)
                    evaluations = by_id
                    break
                except (ModelOutputError, ValueError, KeyError):
                    if attempt == 1:
                        evaluations = {p.candidate_id: failed_evaluation(p, plan.requirements) for p in profiles}
            for profile in profiles:
                cid = profile.candidate_id
                cp.checked_ids.append(cid)
                cp.evaluations[cid] = evaluations[cid]
                rank = evaluation_rank(evaluations[cid], plan.requirements)
                if rank[0] or rank[1] or evaluations[cid].failed:
                    cp.profiles[cid] = profile
            cp.buffered = cp.buffered[count:]
            usage.checked_candidates += count
            await self.save(run_id, snapshot)

    async def continue_run(self, session_id, run_id, user, request_key):
        self.require_enabled()
        async with self.message_lock:
            if not await self.tasks.has_capacity(session_id, self.settings.matching_max_active_tasks):
                raise FeatureDisabledError("当前运行任务已达上限，请稍后重试")
            async with self.uow_factory() as uow:
                session = await owned_session(uow, session_id, user)
                duplicate = await uow.messages.get_by_client_id(session_id, request_key)
                if duplicate:
                    existing = await uow.runs.get_by_trigger(session_id, duplicate.sequence)
                    if existing:
                        return {"run_id": existing.id, "mode": "MATCHING"}
                old, snapshot, plan = await load_run(uow, session_id, run_id, user)
                plan = plan.model_copy(update={
                    "requirements": prefer_non_filter_requirements(plan.requirements),
                }, deep=True)
                if session.active_run_id != run_id or session.current_plan_version != snapshot.plan_version:
                    raise StalePageReferenceError("STALE_CONTINUATION：请从当前需求的最新结果继续")
                if old.status in {"RUNNING", "QUEUED"}:
                    raise StalePageReferenceError("任务仍在运行")
                if (snapshot.checkpoint.round_number >= self.settings.matching_max_rounds
                    or len(snapshot.checkpoint.checked_ids) >= self.settings.matching_max_total_candidates
                    or snapshot.stop_reason == "CONTEXT_LIMIT"):
                    raise StalePageReferenceError("已达到累计轮数限制，请新建需求")
                message, _ = await uow.messages.append_user(session_id, request_key, "继续找 10 位")
                message.route_type = "MATCHING_CONTINUE"
                run = await uow.runs.create(session, message.sequence)
                new = self._new_snapshot(plan, run.id, request_key)
                new.parent_run_id = old.id
                new.continuation_root_run_id = snapshot.continuation_root_run_id
                new.checkpoint = snapshot.checkpoint.model_copy(deep=True)
                new.checkpoint.round_number += 1
                run.result_json = encode_run(new, self.settings.matching_max_snapshot_bytes)
                message.outcome_json = MatchingReplySnapshot(owner_scope=new.owner_scope,
                    run_id=run.id, plan_version=new.plan_version).model_dump(mode="json")
            await self.tasks.start_replacement(session_id, lambda: self.execute(session_id, run.id, user))
        return {"run_id": run.id, "mode": "MATCHING"}

    async def get(self, session_id, run_id, user, include_results=False):
        async with self.uow_factory() as uow:
            run, snapshot, plan = await load_run(uow, session_id, run_id, user)
            session = await owned_session(uow, session_id, user)
            had_legacy_strict_items = bool(
                plan.requirements.required_criteria or plan.requirements.interview_items
            )
            effective_requirements = prefer_non_filter_requirements(plan.requirements)
            provisional_results, provisional_pending = self.choose(snapshot, effective_requirements)
            output_group = list(snapshot.output_group)
            pending_group = list(snapshot.pending_group)
            if had_legacy_strict_items:
                output_group = list(dict.fromkeys(output_group + pending_group))
                pending_group = []
            response = {"run_id": run.id, "status": run.status, "plan_version": snapshot.plan_version,
                        "stop_reason": snapshot.stop_reason, "usage": snapshot.usage.model_dump(),
                        "result_count": len(output_group), "pending_count": len(pending_group),
                        "recalled_count": len(snapshot.checkpoint.checked_ids) + len(snapshot.checkpoint.buffered),
                        "provisional_result_count": len(provisional_results),
                        "provisional_pending_count": len(provisional_pending)}
            response["can_continue"] = (
                session.active_run_id == run_id
                and session.current_plan_version == snapshot.plan_version
                and run.status not in {"RUNNING", "QUEUED"}
                and snapshot.checkpoint.round_number < self.settings.matching_max_rounds
                and len(snapshot.checkpoint.checked_ids) < self.settings.matching_max_total_candidates
                and snapshot.stop_reason != "CONTEXT_LIMIT"
            )
        if not include_results:
            return response
        response["requirements"] = effective_requirements.model_dump(mode="json")
        response["candidates"] = []
        response["pending"] = []
        for field, group in (("candidates", output_group), ("pending", pending_group)):
            for cid in group:
                response[field].append({"card": snapshot.checkpoint.profiles[cid].card.model_dump(),
                    "evaluation": snapshot.checkpoint.evaluations[cid].model_dump(),
                    "profile_sources": [source.model_dump() for source in
                                        snapshot.checkpoint.profiles[cid].sources]})
        return response
