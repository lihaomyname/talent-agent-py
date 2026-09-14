"""用版本化中文招聘话术验证路由和主要结果边界。"""

import json
from pathlib import Path

from talent_agent_py.application.message_router import MessageRouter
from talent_agent_py.domain.enums import MessageType
from talent_agent_py.domain.plan import SearchConditions, SearchPlan
from tests.fakes import FakeLLMClient

CASES_PATH = Path(__file__).with_name("cases.json")


async def test_route_evaluation_cases():
    """评测文件里的路由样例必须保持可执行，避免只保存不运行。"""

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    router = MessageRouter(FakeLLMClient())
    current_plan = SearchPlan(
        version=1,
        applied_through_message_seq=1,
        conditions=SearchConditions(),
    )

    for case in cases:
        if "expected" not in case:
            continue
        expected = MessageType(case["expected"])
        route = await router.route(
            message=case["text"],
            current_plan=current_plan if expected is MessageType.SEARCH_PATCH else None,
            has_pending_clarification=False,
        )
        assert route.message_type is expected, case["text"]
