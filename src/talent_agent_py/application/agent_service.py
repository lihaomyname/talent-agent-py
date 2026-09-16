"""连接消息入口、运行生命周期和 LangGraph 的应用服务。"""

import asyncio
from collections.abc import Callable
from typing import Any

import structlog
from langgraph.graph.state import CompiledStateGraph

from talent_agent_py.application.clarification_service import (
    apply_entity_answer,
    apply_location_answer,
    intent_card,
    validate_answer,
)
from talent_agent_py.application.exceptions import (
    FeatureDisabledError,
    InvalidClarificationAnswerError,
    ModelOutputError,
    RunNotFoundError,
    SessionNotFoundError,
    StalePageReferenceError,
    TalentSearchDeniedError,
    TalentSearchDependencyError,
)
from talent_agent_py.application.message_router import MessageRouter
from talent_agent_py.application.ports.talent_search import TalentSearchPort
from talent_agent_py.application.search_compiler import compile_search_request
from talent_agent_py.domain.conversation import (
    ClarificationAnswer,
    ClarificationCard,
    MessageOutcome,
    MessageRoute,
    PageReference,
    RunView,
    SearchResult,
    UserContext,
)
from talent_agent_py.domain.enums import ClarificationKind, MessageType, ResultStatus, RunStatus
from talent_agent_py.domain.plan import SearchPlan, SearchPlanDraft
from talent_agent_py.infrastructure.persistence.models import RunRecord
from talent_agent_py.infrastructure.persistence.unit_of_work import UnitOfWork
from talent_agent_py.infrastructure.runtime.task_registry import TaskRegistry
from talent_agent_py.orchestration.state import AgentState
from talent_agent_py.settings import Settings
from talent_agent_py.telemetry import INTERRUPTIONS, RUN_OUTCOMES, RUN_STAGES

logger = structlog.get_logger(__name__)


class AgentService:
    """执行一次用户消息，并协调新旧 Run 的简化打断。"""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], UnitOfWork],
        router: MessageRouter,
        graph: CompiledStateGraph[AgentState, None, AgentState, AgentState],
        talent_search: TalentSearchPort,
        task_registry: TaskRegistry,
        settings: Settings,
    ) -> None:
        """注入事务工厂、路由器、已编译 Graph 和招聘客户端，供消息主流程复用。"""

        # 数据库事务工厂；每个 async with 对应一次提交或回滚边界。
        self._uow_factory = uow_factory
        # Graph 之前的消息意图路由器。
        self._router = router
        # 已编译的人才搜索 Graph，输入输出均以 AgentState 描述。
        self._graph = graph
        # 分页路径直接调用的招聘搜索端口。
        self._talent_search = talent_search
        # 当前进程中每个会话的活动异步任务。
        self._tasks = task_registry
        # Agent 开关及搜索策略配置。
        self._settings = settings
        # 搜索被新消息打断时，两个 HTTP 请求会短暂重叠，只串行化消息序号的生成和提交。
        self._message_write_lock = asyncio.Lock()

    @staticmethod
    def _run_view(record: RunRecord) -> RunView:
        """将数据库运行记录转换为 API 展示对象，并还原状态枚举。"""

        return RunView(
            run_id=record.id,
            session_id=record.session_id,
            status=RunStatus(record.status),
            stage=record.stage,
            result_status=ResultStatus(record.result_status) if record.result_status else None,
            error_code=record.error_code,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    async def _load_message_context(
        self, session_id: str, user: UserContext
    ) -> tuple[str | None, SearchPlan | None, ClarificationCard | None]:
        """返回（活动运行 ID、当前计划、待澄清卡），尚未产生的项为 None。"""
        async with self._uow_factory() as uow:
            session_record = await uow.sessions.get_owned(session_id, user.user_id)
            if session_record is None:
                raise SessionNotFoundError("会话不存在")
            return (
                session_record.active_run_id,
                await uow.plans.get_current(session_id),
                await uow.clarifications.get(session_id),
            )

    async def handle_message(
        self,
        *,
        session_id: str,
        client_message_id: str,
        content: str,
        user: UserContext,
        clarification_answer: ClarificationAnswer | None = None,
    ) -> MessageOutcome:
        """保存、路由并执行一条消息；重复消息不会重复调用外部服务。"""

        if not self._settings.enable_agent:
            raise FeatureDisabledError("当前环境尚未开启自然语言找人")

        # 先提交消息，再执行模型和网络调用，避免长时间持有数据库事务。
        async with self._message_write_lock:
            async with self._uow_factory() as uow:
                session_record = await uow.sessions.get_owned(session_id, user.user_id)
                if session_record is None:
                    raise SessionNotFoundError("会话不存在")
                message, created = await uow.messages.append_user(
                    session_id, client_message_id, content
                )
                if not created:
                    existing_run = await uow.runs.get_by_trigger(session_id, message.sequence)
                    if existing_run and existing_run.result_json:
                        return MessageOutcome(
                            kind="RESULT",
                            result=self._bounded_result(existing_run.result_json),
                        )
                    if existing_run:
                        return MessageOutcome(kind="STATUS", run=self._run_view(existing_run))
                    return MessageOutcome(kind="CHAT", reply="这条消息已经收到。")

        active_run_id, current_plan, pending = await self._load_message_context(session_id, user)
        route = await self._router.route(
            message=content,
            current_plan=current_plan,
            has_pending_clarification=pending is not None,
            structured_clarification=clarification_answer is not None,
        )

        async with self._uow_factory() as uow:
            stored_message = await uow.messages.get_by_client_id(session_id, client_message_id)
            if stored_message is None:
                raise RuntimeError("已提交的消息记录无法重新读取")
            stored_message.route_type = route.message_type.value

        if route.message_type is MessageType.CASUAL_CHAT:
            return MessageOutcome(kind="CHAT", reply="你好，可以继续补充找人条件。")
        if route.message_type is MessageType.STATUS_QUERY:
            if not active_run_id:
                return MessageOutcome(kind="CHAT", reply="当前没有正在执行的搜索。")
            return MessageOutcome(kind="STATUS", run=await self.get_run(active_run_id, user))
        if route.message_type is MessageType.CONTROL_STOP:
            return await self._stop(session_id, active_run_id, user)
        if route.message_type is MessageType.PAGE_ACTION:
            if current_plan is None:
                raise StalePageReferenceError("当前没有可分页的搜索计划")
            current_result = await self.get_result(session_id, user)
            if current_result is None:
                raise StalePageReferenceError("当前没有可分页的搜索结果")
            target_page = max(1, current_result.page + (route.page_delta or 1))
            return await self.get_page(
                PageReference(
                    session_id=session_id,
                    plan_version=current_plan.version,
                    page=target_page,
                ),
                user,
            )
        if route.message_type is MessageType.UNKNOWN:
            return await self._store_intent_clarification(
                session_id,
                stored_message.sequence,
                current_plan,
                user,
                active_run_id=active_run_id,
                existing_card=pending,
            )

        # 卡片答案直接恢复已保存草稿，避免将用户已确认的条件重新交给模型猜测。
        initial_draft = None
        entities_resolved = False
        if clarification_answer:
            immediate = await self._handle_non_search_answer(
                session_id, clarification_answer, user
            )
            if immediate is not None:
                return immediate
            initial_draft, entities_resolved = await self._apply_structured_answer(
                session_id, clarification_answer, user
            )

        return await self._start_search_run(
            session_id=session_id,
            message_sequence=stored_message.sequence,
            user=user,
            route=route,
            old_run_id=active_run_id,
            initial_draft=initial_draft,
            entities_resolved=entities_resolved,
        )

    async def _handle_non_search_answer(
        self,
        session_id: str,
        answer: ClarificationAnswer,
        user: UserContext,
    ) -> MessageOutcome | None:
        """处理只结束澄清、不应立即启动搜索的结构化答案。"""

        async with self._uow_factory() as uow:
            session_record = await uow.sessions.get_owned(session_id, user.user_id)
            if session_record is None:
                raise SessionNotFoundError("会话不存在")
            pending = await uow.clarifications.get_with_draft(session_id)
            if pending is None:
                return None
            card, _ = pending
            validate_answer(card, answer)
            if card.kind is ClarificationKind.MESSAGE_INTENT:
                await uow.clarifications.clear(session_id)
                reply = (
                    "好的，这句话不会修改当前搜索。"
                    if answer.value == "CASUAL_CHAT"
                    else "请继续描述要修改的搜索条件。"
                )
                return MessageOutcome(kind="CHAT", reply=reply)
            if (
                card.kind
                in {ClarificationKind.UNSUPPORTED_CONDITION, ClarificationKind.ENTITY_NOT_FOUND}
                and answer.value == "RESTATE"
            ):
                await uow.clarifications.clear(session_id)
                return MessageOutcome(kind="CHAT", reply="请重新描述要执行的搜索条件。")
        return None

    async def _apply_structured_answer(
        self,
        session_id: str,
        answer: ClarificationAnswer,
        user: UserContext,
    ) -> tuple[SearchPlanDraft, bool]:
        """校验当前卡片并回填草稿。返回（更新后的草稿、是否可跳过实体解析）。"""

        async with self._uow_factory() as uow:
            session_record = await uow.sessions.get_owned(session_id, user.user_id)
            if session_record is None:
                raise SessionNotFoundError("会话不存在")
            pending = await uow.clarifications.get_with_draft(session_id)
            if pending is None:
                raise InvalidClarificationAnswerError("当前没有待回答的澄清问题")
            card, draft = pending
            if draft is None:
                raise InvalidClarificationAnswerError("该澄清问题不能直接继续搜索")
            validate_answer(card, answer)
            if card.kind is ClarificationKind.LOCATION_SCOPE:
                return apply_location_answer(draft, card, answer), False
            if card.kind is ClarificationKind.ENTITY_AMBIGUITY:
                # 草稿中的其他解析结果同样来自上一次 Java 调用，可跳过重复解析；
                # 学历和年限是模型产生的语义澄清，其他实体可能尚未解析，需要继续解析。
                entities_resolved = card.field not in {"minimum_degree", "work_years"}
                return apply_entity_answer(draft, card, answer), entities_resolved
            if card.kind is ClarificationKind.UNSUPPORTED_CONDITION:
                if answer.value != "IGNORE":
                    raise InvalidClarificationAnswerError("请重新描述可执行的搜索条件")
                data = draft.model_dump(mode="python")
                data["unsupported_conditions"] = data["unsupported_conditions"][1:]
                return SearchPlanDraft.model_validate(data), False
            if card.kind is ClarificationKind.ENTITY_NOT_FOUND:
                if answer.value != "IGNORE":
                    raise InvalidClarificationAnswerError("请重新描述可执行的搜索条件")
                return self._remove_unresolved_entity(draft, card.field), False
            raise InvalidClarificationAnswerError("该类型澄清需要重新描述搜索条件")

    @staticmethod
    def _remove_unresolved_entity(draft: SearchPlanDraft, field: str) -> SearchPlanDraft:
        """按受控字段路径删除未找到的条件值，并移除对应阻塞项。"""

        data = draft.model_dump(mode="python")
        conditions = data["conditions"]
        if ":" in field:
            field_name, raw_index = field.split(":", 1)
            values_key = "labels" if field_name == "school_level" else "names"
            condition = conditions.get(field_name)
            if condition is not None and raw_index.isdigit():
                index = int(raw_index)
                values = condition.get(values_key, [])
                if 0 <= index < len(values):
                    values.pop(index)
                if not values:
                    conditions[field_name] = None
        elif field in {"minimum_degree", "current_city", "expected_city"}:
            conditions[field] = None
        else:
            raise InvalidClarificationAnswerError("无法忽略该实体条件")
        data["ambiguities"] = [
            item for item in data["ambiguities"] if item["field"] != field
        ]
        return SearchPlanDraft.model_validate(data)

    async def _start_search_run(
        self,
        *,
        session_id: str,
        message_sequence: int,
        user: UserContext,
        route: MessageRoute,
        old_run_id: str | None,
        initial_draft: SearchPlanDraft | None,
        entities_resolved: bool = False,
    ) -> MessageOutcome:
        """创建新运行并替代旧任务，返回搜索结果或已被替代的结果响应。"""

        async with self._uow_factory() as uow:
            session_record = await uow.sessions.get_owned(session_id, user.user_id)
            if session_record is None:
                raise SessionNotFoundError("会话不存在")
            run = await uow.runs.create(session_record, message_sequence)
            if old_run_id and old_run_id != run.id:
                await uow.runs.mark_superseded(old_run_id, run.id)

        async def execute_replacement() -> SearchResult:
            """等待旧任务收尾后执行新 Graph，返回新运行的业务结果。"""

            return await self._execute_graph(
                session_id=session_id,
                run_id=run.id,
                message_sequence=message_sequence,
                user=user,
                route=route,
                initial_draft=initial_draft,
                entities_resolved=entities_resolved,
            )

        # 同一会话的新 Run 会先等待旧 Run 完成必要的数据库收尾。
        task = await self._tasks.start_replacement(session_id, execute_replacement)
        try:
            result = await task
            return MessageOutcome(kind="RESULT", result=result)
        except asyncio.CancelledError:
            INTERRUPTIONS.labels("superseded").inc()
            logger.info("运行被新消息替代", session_id=session_id, run_id=run.id)
            return MessageOutcome(
                kind="RESULT",
                result=SearchResult(
                    status=ResultStatus.SUPERSEDED,
                    run_id=run.id,
                    plan_version=0,
                    message="本轮搜索已被更新的条件替代。",
                ),
            )
        finally:
            await self._tasks.remove(session_id, task)

    async def _execute_graph(
        self,
        *,
        session_id: str,
        run_id: str,
        message_sequence: int,
        user: UserContext,
        route: MessageRoute,
        initial_draft: SearchPlanDraft | None,
        entities_resolved: bool,
    ) -> SearchResult:
        """执行 Graph 并取出最终 SearchResult；将模型和依赖异常转成可展示结果。"""

        async with self._uow_factory() as uow:
            await uow.runs.update(run_id, status=RunStatus.RUNNING, stage="load_context")
        try:
            final_state = await self._graph.ainvoke({
                "session_id": session_id,
                "run_id": run_id,
                "trigger_message_sequence": message_sequence,
                "user": user,
                "route": route,
                "entities_resolved": entities_resolved,
                **({"draft": initial_draft} if initial_draft else {}),
            })
            return final_state["result"]
        except asyncio.CancelledError:
            async with self._uow_factory() as uow:
                run = await uow.runs.get(run_id)
                if run and run.status != RunStatus.CANCELLED.value:
                    await uow.runs.update(
                        run_id, status=RunStatus.SUPERSEDED, stage="cancelled"
                    )
            raise
        except ModelOutputError as exc:
            logger.warning(
                "大模型阶段失败",
                session_id=session_id,
                run_id=run_id,
                error=str(exc),
            )
            return await self._finish_error(
                run_id,
                ResultStatus.MODEL_ERROR,
                "MODEL_ERROR",
                message=str(exc),
            )
        except TalentSearchDeniedError:
            return await self._finish_error(run_id, ResultStatus.DENIED, "DENIED")
        except TalentSearchDependencyError:
            return await self._finish_error(run_id, ResultStatus.DEPENDENCY_ERROR, "DEPENDENCY_ERROR")
        except Exception:
            logger.exception("图执行发生未分类异常", session_id=session_id, run_id=run_id)
            return await self._finish_error(
                run_id, ResultStatus.INTERNAL_ERROR, "INTERNAL_ERROR"
            )

    async def _finish_error(
        self,
        run_id: str,
        status: ResultStatus,
        code: str,
        *,
        message: str = "本轮处理失败，请稍后重试。",
    ) -> SearchResult:
        """保存失败运行的状态与错误结果，返回供前端展示的 SearchResult。"""

        async with self._uow_factory() as uow:
            existing = await uow.runs.get(run_id)
            if existing is not None and existing.status in {
                RunStatus.CANCELLED.value,
                RunStatus.SUPERSEDED.value,
            }:
                return SearchResult(
                    status=ResultStatus(existing.status),
                    run_id=run_id,
                    plan_version=0,
                    message="本轮搜索已停止或被新条件替代。",
                )
            run = await uow.runs.update(
                run_id,
                status=RunStatus.FAILED,
                stage="failed",
                result_status=status.value,
                error_code=code,
            )
            result = SearchResult(
                status=status,
                run_id=run_id,
                plan_version=0,
                message=message,
            )
            run.result_json = result.model_dump(mode="json")
            RUN_OUTCOMES.labels(status.value).inc()
            RUN_STAGES.labels("failed").inc()
            return result

    async def _stop(
        self, session_id: str, run_id: str | None, user: UserContext
    ) -> MessageOutcome:
        """取消当前运行并返回停止结果；已完成运行沿用其终态。"""

        await self._tasks.cancel(session_id)
        INTERRUPTIONS.labels("explicit_stop").inc()
        logger.info("用户取消运行", session_id=session_id, run_id=run_id)
        if not run_id:
            return MessageOutcome(kind="CHAT", reply="当前没有正在执行的搜索。")
        async with self._uow_factory() as uow:
            session_record = await uow.sessions.get_owned(session_id, user.user_id)
            if session_record is None:
                raise SessionNotFoundError("会话不存在")
            run = await uow.runs.get(run_id)
            if run is None:
                raise RunNotFoundError("运行记录不存在")
            if run.status not in {
                RunStatus.SUCCEEDED.value,
                RunStatus.FAILED.value,
                RunStatus.CANCELLED.value,
                RunStatus.SUPERSEDED.value,
            }:
                run = await uow.runs.update(
                    run_id,
                    status=RunStatus.CANCELLED,
                    stage="cancelled",
                    result_status=ResultStatus.CANCELLED.value,
                )
        return MessageOutcome(kind="STATUS", run=self._run_view(run))

    async def _store_intent_clarification(
        self,
        session_id: str,
        message_sequence: int,
        current_plan: SearchPlan | None,
        user: UserContext,
        *,
        active_run_id: str | None,
        existing_card: ClarificationCard | None = None,
    ) -> MessageOutcome:
        """保存消息意图卡并返回澄清响应；不主动取消原搜索。"""

        card = existing_card or intent_card()
        async with self._uow_factory() as uow:
            session_record = await uow.sessions.get_owned(session_id, user.user_id)
            if session_record is None:
                raise SessionNotFoundError("会话不存在")
            if existing_card is not None and active_run_id:
                run = await uow.runs.get(active_run_id)
                if run is None:
                    raise RunNotFoundError("运行记录不存在")
            else:
                # 运行中的搜索保持 active；意图澄清作为旁路记录，不主动取消它。
                run = await uow.runs.create(
                    session_record,
                    message_sequence,
                    activate=active_run_id is None,
                )
                await uow.clarifications.save(session_id, message_sequence, card)
                await uow.runs.update(
                    run.id,
                    status=RunStatus.NEEDS_CLARIFICATION,
                    stage="message_intent_clarification",
                    result_status=ResultStatus.NEEDS_CLARIFICATION.value,
                )
        return MessageOutcome(kind="RESULT", result=SearchResult(
            status=ResultStatus.NEEDS_CLARIFICATION,
            run_id=run.id,
            plan_version=current_plan.version if current_plan else 0,
            clarification=card,
        ))

    async def get_run(self, run_id: str, user: UserContext) -> RunView:
        """检查会话归属后返回运行视图；运行或所属会话不可访问时抛出业务异常。"""

        async with self._uow_factory() as uow:
            run = await uow.runs.get(run_id)
            if run is None:
                raise RunNotFoundError("运行记录不存在")
            session_record = await uow.sessions.get_owned(run.session_id, user.user_id)
            if session_record is None:
                raise RunNotFoundError("运行记录不存在")
            return self._run_view(run)

    async def cancel_current(
        self, session_id: str, user: UserContext
    ) -> MessageOutcome:
        """取消当前用户会话的 active Run。"""

        active_run_id, _, _ = await self._load_message_context(session_id, user)
        return await self._stop(session_id, active_run_id, user)

    async def get_result(self, session_id: str, user: UserContext) -> SearchResult | None:
        """返回会话活动运行的已保存结果；没有运行或结果时返回 None。"""

        async with self._uow_factory() as uow:
            session_record = await uow.sessions.get_owned(session_id, user.user_id)
            if session_record is None:
                raise SessionNotFoundError("会话不存在")
            if not session_record.active_run_id:
                return None
            run = await uow.runs.get(session_record.active_run_id)
            return (
                self._bounded_result(run.result_json)
                if run and run.result_json else None
            )

    def _bounded_result(self, payload: dict[str, Any]) -> SearchResult:
        """兼容旧运行快照，并保证恢复历史时每页也只展示 10 条。"""

        result = SearchResult.model_validate(payload, strict=False)
        if len(result.candidates) <= self._settings.default_page_size:
            return result
        data = result.model_dump(mode="python")
        data["candidates"] = data["candidates"][: self._settings.default_page_size]
        return SearchResult.model_validate(data)

    async def get_page(
        self, reference: PageReference, user: UserContext
    ) -> MessageOutcome:
        """不调用 LLM，直接按当前计划读取指定页。"""

        async with self._uow_factory() as uow:
            session_record = await uow.sessions.get_owned(reference.session_id, user.user_id)
            if session_record is None:
                raise SessionNotFoundError("会话不存在")
            plan = await uow.plans.get_current(reference.session_id)
            if plan is None or plan.version != reference.plan_version:
                raise StalePageReferenceError("分页引用已失效")
            run = await uow.runs.create(
                session_record, None, activate=False
            )

        request = compile_search_request(plan, self._settings, page=reference.page)
        response = await self._talent_search.search_candidates(request, user)
        status = ResultStatus.OK if response.candidates else ResultStatus.EMPTY
        next_page = (
            PageReference(
                session_id=reference.session_id,
                plan_version=plan.version,
                page=reference.page + 1,
            )
            if response.has_next else None
        )
        result = SearchResult(
            status=status,
            run_id=run.id,
            plan_version=plan.version,
            page=reference.page,
            candidates=response.candidates,
            total=response.total,
            next_page=next_page,
            executed_conditions=plan.conditions,
        )
        async with self._uow_factory() as uow:
            await uow.runs.update(
                run.id,
                status=RunStatus.SUCCEEDED,
                stage="completed",
                result_status=status.value,
                result_json=result.model_dump(mode="json"),
            )
        return MessageOutcome(kind="RESULT", result=result)
