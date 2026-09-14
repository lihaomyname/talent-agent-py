"""自然语言找人 V1 的 LangGraph 节点。"""

import time
from collections.abc import Callable
from dataclasses import dataclass

import structlog
from pydantic import ValidationError

from talent_agent_py.application.clarification_service import (
    entity_ambiguity_card,
    entity_not_found_card,
    intent_card,
    location_scope_card,
    unsupported_condition_card,
)
from talent_agent_py.application.entity_resolution import resolve_draft_entities
from talent_agent_py.application.exceptions import ModelOutputError
from talent_agent_py.application.plan_validation import (
    enforce_location_scope_clarification,
    validate_draft,
)
from talent_agent_py.application.ports.llm import LLMClient
from talent_agent_py.application.ports.talent_search import TalentSearchPort
from talent_agent_py.application.search_compiler import compile_search_request
from talent_agent_py.domain.conversation import PageReference, SearchResult
from talent_agent_py.domain.enums import MessageType, ResultStatus, RunStatus
from talent_agent_py.domain.plan import (
    ResolvedEntity,
    SearchPlan,
    SearchPlanDraft,
    apply_plan_patch,
)
from talent_agent_py.infrastructure.persistence.unit_of_work import UnitOfWork
from talent_agent_py.orchestration.interruptible import complete_before_cancel, interruptible
from talent_agent_py.orchestration.state import AgentState
from talent_agent_py.settings import Settings
from talent_agent_py.telemetry import (
    CLARIFICATIONS,
    EXTERNAL_CALLS,
    JAVA_LATENCY,
    PARSE_OUTCOMES,
    RUN_OUTCOMES,
    RUN_STAGES,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class GraphDependencies:
    """图节点共享的端口和资源工厂。"""

    uow_factory: Callable[[], UnitOfWork]
    llm: LLMClient
    talent_search: TalentSearchPort
    settings: Settings


class TalentSearchNodes:
    """把节点依赖封装在一个可测试对象中。"""

    def __init__(self, dependencies: GraphDependencies) -> None:
        self._deps = dependencies

    @staticmethod
    def _superseded_result(state: AgentState) -> SearchResult:
        """为已被替代的旧图生成只读结果，不覆盖最新会话状态。"""

        current_plan = state.get("current_plan")
        return SearchResult(
            status=ResultStatus.SUPERSEDED,
            run_id=state["run_id"],
            plan_version=current_plan.version if current_plan else 0,
            message="本轮搜索已被更新的条件替代。",
        )

    async def load_context(self, state: AgentState) -> dict:
        """加载当前计划和尚未被计划吸收的用户消息。"""

        RUN_STAGES.labels("load_context").inc()
        async with self._deps.uow_factory() as uow:
            plan = await uow.plans.get_current(state["session_id"])
            applied = plan.applied_through_message_seq if plan else 0
            records = await uow.messages.list_after(
                state["session_id"],
                applied,
                through=state["trigger_message_sequence"],
            )
        return {
            "current_plan": plan,
            "messages": [record.content for record in records],
        }

    @interruptible
    async def parse_plan(self, state: AgentState) -> dict:
        """首次搜索生成草稿，后续搜索只生成并应用 PlanPatch。"""

        if state.get("draft") is not None:
            return {}
        current_plan = state.get("current_plan")
        route_type = state["route"].message_type
        if current_plan and route_type is MessageType.SEARCH_PATCH:
            EXTERNAL_CALLS.labels("llm", "parse_plan_patch").inc()
            try:
                patch = await self._deps.llm.parse_plan_patch(
                    messages=state["messages"],
                    current_plan=current_plan,
                )
            except Exception:
                PARSE_OUTCOMES.labels("plan_patch", "error").inc()
                raise
            PARSE_OUTCOMES.labels("plan_patch", "success").inc()
            if patch.base_plan_version != current_plan.version:
                raise ModelOutputError("PlanPatch 基础版本与当前计划不一致")
            try:
                draft = SearchPlanDraft(
                    conditions=apply_plan_patch(current_plan.conditions, patch),
                    unsupported_conditions=patch.unsupported_conditions,
                    ambiguities=patch.ambiguities,
                )
            except ValidationError as exc:
                raise ModelOutputError("大模型生成的计划修改字段结构不正确") from exc
            draft = enforce_location_scope_clarification(
                draft,
                state["messages"],
                previous_conditions=current_plan.conditions,
            )
            return {"patch": patch, "draft": draft}

        EXTERNAL_CALLS.labels("llm", "parse_search_draft").inc()
        try:
            draft = await self._deps.llm.parse_search_draft(messages=state["messages"])
        except Exception:
            PARSE_OUTCOMES.labels("search_draft", "error").inc()
            raise
        PARSE_OUTCOMES.labels("search_draft", "success").inc()
        draft = enforce_location_scope_clarification(draft, state["messages"])
        return {"draft": draft}

    async def validate(self, state: AgentState) -> dict:
        """执行确定性范围、冲突和阻塞项校验。"""

        return {"validation": validate_draft(state["draft"])}

    @interruptible
    async def resolve_entities(self, state: AgentState) -> dict:
        """所有业务 code 都通过 Java 解析，模型输出不被信任。"""

        EXTERNAL_CALLS.labels("java", "resolve_entities").inc()
        started = time.perf_counter()
        try:
            draft = await resolve_draft_entities(
                state["draft"],
                self._deps.talent_search,
                state["user"],
            )
        finally:
            JAVA_LATENCY.labels("resolve_entities").observe(time.perf_counter() - started)
        return {"draft": draft, "validation": validate_draft(draft)}

    async def clarify(self, state: AgentState) -> dict:
        """生成固定卡片并保存当前草稿，HTTP 请求随后正常结束。"""

        draft = state["draft"]
        if draft.unsupported_conditions:
            card = unsupported_condition_card(draft.unsupported_conditions[0])
        elif draft.unresolved_location:
            card = location_scope_card(draft.unresolved_location)
        elif state["validation"].ambiguities:
            ambiguity = state["validation"].ambiguities[0]
            entity_options = ambiguity.entity_options or [
                ResolvedEntity(code=option, label=option)
                for option in ambiguity.options
            ]
            card = (
                entity_ambiguity_card(field=ambiguity.field, options=entity_options)
                if entity_options
                else entity_not_found_card(
                    field=ambiguity.field,
                    input_text=ambiguity.input_text,
                )
            )
        else:
            card = intent_card()

        async with self._deps.uow_factory() as uow:
            session_record = await uow.sessions.get_owned(
                state["session_id"], state["user"].user_id
            )
            if session_record is None or session_record.active_run_id != state["run_id"]:
                return {"result": self._superseded_result(state)}
            await uow.clarifications.save(
                state["session_id"],
                state["trigger_message_sequence"],
                card,
                draft,
            )
            result_status = (
                ResultStatus.UNSUPPORTED
                if draft.unsupported_conditions
                else ResultStatus.NEEDS_CLARIFICATION
            )
            run = await uow.runs.update(
                state["run_id"],
                status=RunStatus.NEEDS_CLARIFICATION,
                stage="clarification",
                result_status=result_status.value,
            )
        CLARIFICATIONS.labels(card.kind.value).inc()
        RUN_STAGES.labels("clarification").inc()
        logger.info(
            "生成澄清卡",
            session_id=state["session_id"],
            run_id=state["run_id"],
            clarification_kind=card.kind.value,
        )
        result = SearchResult(
            status=(
                ResultStatus.UNSUPPORTED
                if draft.unsupported_conditions
                else ResultStatus.NEEDS_CLARIFICATION
            ),
            run_id=state["run_id"],
            plan_version=state.get("current_plan").version if state.get("current_plan") else 0,
            executed_conditions=(
                state.get("current_plan").conditions if state.get("current_plan") else None
            ),
            clarification=card,
        )
        async with self._deps.uow_factory() as uow:
            run = await uow.runs.get(state["run_id"])
            if run:
                run.result_json = result.model_dump(mode="json")
        return {"clarification": card, "result": result}

    @complete_before_cancel
    async def save_plan(self, state: AgentState) -> dict:
        """数据库保存开始后允许完成；新的用户消息将在下一版本继续修改。"""

        RUN_STAGES.labels("save_plan").inc()
        current = state.get("current_plan")
        plan = SearchPlan(
            version=(current.version + 1) if current else 1,
            applied_through_message_seq=state["trigger_message_sequence"],
            conditions=state["draft"].conditions,
            unsupported_conditions=tuple(state["draft"].unsupported_conditions),
        )
        async with self._deps.uow_factory() as uow:
            session_record = await uow.sessions.get_owned(
                state["session_id"], state["user"].user_id
            )
            if session_record is None:
                raise LookupError("session disappeared while saving plan")
            await uow.plans.save(session_record, plan)
            await uow.clarifications.clear(state["session_id"])
        return {"current_plan": plan}

    async def compile_search(self, state: AgentState) -> dict:
        """将计划映射为固定的 Java Tool 输入。"""

        return {
            "search_request": compile_search_request(
                state["current_plan"], self._deps.settings
            )
        }

    @interruptible
    async def search_candidates(self, state: AgentState) -> dict:
        """调用 Java 权威搜索并保留原始排序。"""

        EXTERNAL_CALLS.labels("java", "search_candidates").inc()
        RUN_STAGES.labels("search_candidates").inc()
        started = time.perf_counter()
        try:
            response = await self._deps.talent_search.search_candidates(
                state["search_request"], state["user"]
            )
        finally:
            JAVA_LATENCY.labels("search_candidates").observe(time.perf_counter() - started)
        return {"search_response": response}

    async def finalize(self, state: AgentState) -> dict:
        """生成与当前 runId 和 planVersion 绑定的最终结果。"""

        response = state["search_response"]
        plan = state["current_plan"]
        status = ResultStatus.OK if response.candidates else ResultStatus.EMPTY
        next_page = None
        if response.has_next:
            next_page = PageReference(
                session_id=state["session_id"],
                plan_version=plan.version,
                page=state["search_request"].currentPage + 1,
            )
        result = SearchResult(
            status=status,
            run_id=state["run_id"],
            plan_version=plan.version,
            page=state["search_request"].currentPage,
            candidates=response.candidates,
            total=response.total,
            next_page=next_page,
            executed_conditions=plan.conditions,
        )
        async with self._deps.uow_factory() as uow:
            session_record = await uow.sessions.get_owned(
                state["session_id"], state["user"].user_id
            )
            if session_record is None or session_record.active_run_id != state["run_id"]:
                return {"result": self._superseded_result(state)}
            await uow.runs.update(
                state["run_id"],
                status=RunStatus.SUCCEEDED,
                stage="completed",
                result_status=status.value,
                result_json=result.model_dump(mode="json"),
            )
        RUN_OUTCOMES.labels(status.value).inc()
        RUN_STAGES.labels("completed").inc()
        logger.info(
            "人才搜索完成",
            session_id=state["session_id"],
            run_id=state["run_id"],
            plan_version=plan.version,
            result_status=status.value,
            result_count=response.total,
        )
        return {"result": result}
