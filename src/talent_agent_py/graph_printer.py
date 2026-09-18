"""打印并导出自然语言找人的 LangGraph 拓扑。"""

from argparse import ArgumentParser
from pathlib import Path
from unittest.mock import Mock

from langgraph.graph.state import CompiledStateGraph

from talent_agent_py.orchestration.graph import build_graph
from talent_agent_py.orchestration.nodes import GraphDependencies
from talent_agent_py.orchestration.state import AgentState


def _build_graph_for_drawing() -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    """使用占位依赖构建真实 Graph；绘图不会执行任何业务节点。"""

    dependencies = GraphDependencies(
        uow_factory=Mock(name="uow_factory"),
        llm=Mock(name="llm_client"),
        talent_search=Mock(name="talent_search_client"),
        settings=Mock(name="settings"),
    )
    return build_graph(dependencies)


def main() -> None:
    """在控制台打印 Mermaid，并同时保存 Mermaid 和 PNG 文件。"""

    parser = ArgumentParser(description="打印并导出 Talent Agent 的 LangGraph")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/graphs"),
        help="图文件输出目录，默认 artifacts/graphs",
    )
    args = parser.parse_args()

    drawable_graph = _build_graph_for_drawing().get_graph()
    mermaid = drawable_graph.draw_mermaid()

    # Mermaid 文本适合代码评审，也可以直接粘贴到支持 Mermaid 的 Markdown 中。
    print("\n===== Talent Agent LangGraph（Mermaid）=====\n")
    print(mermaid)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    mermaid_path = args.output_dir / "talent-search-graph.mmd"
    png_path = args.output_dir / "talent-search-graph.png"
    mermaid_path.write_text(mermaid, encoding="utf-8")

    # draw_mermaid_png 使用 LangGraph 官方绘图能力，不会触发图中的业务节点。
    png_path.write_bytes(drawable_graph.draw_mermaid_png())

    print(f"\nMermaid 文件：{mermaid_path.resolve()}")
    print(f"PNG 图片：{png_path.resolve()}")


if __name__ == "__main__":
    main()
