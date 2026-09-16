"""自然语言找人 V1 固定状态图。"""

from collections.abc import Awaitable, Callable
from typing import TypeVar

import structlog
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from talent_agent_py.orchestration.nodes import GraphDependencies, TalentSearchNodes
from talent_agent_py.orchestration.state import AgentState
from talent_agent_py.telemetry import sanitize_log_value

logger = structlog.get_logger(__name__)

# 保留被包装节点的返回类型，让 IDE 能显示每个节点具体更新哪些字段。
NodeOutput = TypeVar("NodeOutput")


def _with_node_log(
    node_name: str,
    node: Callable[[AgentState], Awaitable[NodeOutput]],
) -> Callable[[AgentState], Awaitable[NodeOutput]]:
    """统一包装节点进入、完成和异常日志，避免每个节点重复写模板代码。"""

    async def logged_node(state: AgentState) -> NodeOutput:
        """执行原节点并记录开始、完成或异常，原样返回该节点的状态更新。"""

        common = {
            "node": node_name,
            "session_id": state.get("session_id"),
            "run_id": state.get("run_id"),
        }
        logger.info("LangGraph 节点开始", **common)
        try:
            output = await node(state)
        except BaseException as exc:
            logger.warning(
                "LangGraph 节点结束（异常）",
                **common,
                exception_type=type(exc).__name__,
                exception_message=str(exc),
            )
            raise
        logger.info(
            "LangGraph 节点完成",
            **common,
            output=sanitize_log_value(output),
        )
        return output

    return logged_node


def _after_validation(state: AgentState) -> str:
    """先处理阻塞项；只有完全可执行时才继续调用 Java。"""

    validation = state["validation"]
    if not validation.executable:
        return "clarify"
    return "save_plan" if state.get("entities_resolved") else "resolve_entities"


def _after_resolution(state: AgentState) -> str:
    """实体多义或未找到时返回澄清卡，否则保存计划。"""

    validation = state["validation"]
    return "clarify" if not validation.executable else "save_plan"


def build_graph(
    dependencies: GraphDependencies,
) -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """构建代码控制的 StateGraph，不允许模型动态增加工具或边。"""

    nodes = TalentSearchNodes(dependencies)
    graph = StateGraph(AgentState)
    graph.add_node("load_context", _with_node_log("load_context", nodes.load_context))
    graph.add_node("parse_plan", _with_node_log("parse_plan", nodes.parse_plan))
    graph.add_node("validate", _with_node_log("validate", nodes.validate))
    graph.add_node(
        "resolve_entities", _with_node_log("resolve_entities", nodes.resolve_entities)
    )
    graph.add_node("clarify", _with_node_log("clarify", nodes.clarify))
    graph.add_node("save_plan", _with_node_log("save_plan", nodes.save_plan))
    graph.add_node(
        "compile_search", _with_node_log("compile_search", nodes.compile_search)
    )
    graph.add_node(
        "search_candidates", _with_node_log("search_candidates", nodes.search_candidates)
    )
    graph.add_node("finalize", _with_node_log("finalize", nodes.finalize))

    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "parse_plan")
    graph.add_edge("parse_plan", "validate")
    graph.add_conditional_edges(
        "validate",
        _after_validation,
        {
            "clarify": "clarify",
            "resolve_entities": "resolve_entities",
            "save_plan": "save_plan",
        },
    )
    graph.add_conditional_edges(
        "resolve_entities",
        _after_resolution,
        {"clarify": "clarify", "save_plan": "save_plan"},
    )
    graph.add_edge("clarify", END)
    graph.add_edge("save_plan", "compile_search")
    graph.add_edge("compile_search", "search_candidates")
    graph.add_edge("search_candidates", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()
