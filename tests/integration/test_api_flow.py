"""从会话消息到 Java 结果的完整 API 流程测试。"""

import asyncio

import httpx
from fastapi.testclient import TestClient

from talent_agent_py.application.exceptions import (
    ModelOutputError,
    TalentSearchDeniedError,
    TalentSearchDependencyError,
)
from talent_agent_py.application.ports.talent_search import (
    EntityCandidate,
    EntityResolution,
)
from talent_agent_py.domain.enums import EntityResolutionStatus, LocationScope
from talent_agent_py.domain.plan import LocationCondition, SearchConditions, SearchPlanDraft
from talent_agent_py.main import create_app
from talent_agent_py.settings import Settings
from tests.fakes import FakeLLMClient, FakeTalentSearch


def build_client(tmp_path, llm=None, talent=None):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'agent.db'}",
        auto_create_schema=True,
    )
    app = create_app(
        settings,
        llm_client=llm or FakeLLMClient(),
        talent_search_client=talent or FakeTalentSearch(),
    )
    return TestClient(app)


def test_frontend_entry_and_static_assets_are_available(tmp_path):
    """会话首页和本地静态资源应由同一个 FastAPI 服务提供。"""
    with build_client(tmp_path) as client:
        page = client.get("/")
        script = client.get("/static/app.js")
        icon_font = client.get("/static/vendor/fonts/bootstrap-icons.woff2")

        assert page.status_code == 200
        assert "自然语言找人" in page.text
        assert script.status_code == 200
        assert icon_font.status_code == 200


def test_session_history_is_loaded_from_database_and_isolated_by_user(tmp_path):
    """重新打开页面后，应能按用户从数据库恢复会话列表。"""

    with build_client(tmp_path) as client:
        owner_headers = {"X-User-Id": "owner"}
        other_headers = {"X-User-Id": "other"}
        session_id = client.post("/api/v1/sessions", headers=owner_headers).json()["session_id"]
        client.post(
            f"/api/v1/sessions/{session_id}/messages",
            headers=owner_headers,
            json={"client_message_id": "history-1", "content": "找Java后端，现居杭州"},
        )

        owner_history = client.get("/api/v1/sessions", headers=owner_headers)
        other_history = client.get("/api/v1/sessions", headers=other_headers)

        assert owner_history.status_code == 200
        assert owner_history.json()[0]["session_id"] == session_id
        assert owner_history.json()[0]["title"] == "找Java后端，现居杭州"
        assert other_history.json() == []


def test_complete_search_flow(tmp_path):
    talent = FakeTalentSearch()
    with build_client(tmp_path, talent=talent) as client:
        headers = {"X-User-Id": "user-1"}
        session = client.post("/api/v1/sessions", headers=headers).json()
        response = client.post(
            f"/api/v1/sessions/{session['session_id']}/messages",
            headers=headers,
            json={
                "client_message_id": "message-1",
                "content": "找张三，Java后端，本科，3到5年，在网易工作过，浙江大学，现居杭州，985",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["result"]["status"] == "OK"
        assert body["result"]["plan_version"] == 1
        assert body["result"]["candidates"][0]["candidate_id"] == "candidate-1"
        assert talent.last_request.topDegree == "06"
        assert talent.last_request.livePlace == [330100]
        assert talent.last_request.pageSize == 10
        assert talent.last_request.hideClue is True


def test_location_clarification_round_trip_without_second_llm_parse(tmp_path):
    llm = FakeLLMClient()
    with build_client(tmp_path, llm=llm) as client:
        headers = {"X-User-Id": "user-1"}
        session_id = client.post("/api/v1/sessions", headers=headers).json()["session_id"]
        first = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            headers=headers,
            json={"client_message_id": "m1", "content": "找Java后端，杭州"},
        ).json()
        card = first["result"]["clarification"]
        assert first["result"]["status"] == "NEEDS_CLARIFICATION"

        second = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            headers=headers,
            json={
                "client_message_id": "m2",
                "content": "现居住地",
                "clarification_answer": {
                    "question_id": card["question_id"],
                    "value": "CURRENT_CITY",
                },
            },
        )
        assert second.status_code == 200, second.text
        assert second.json()["result"]["status"] == "OK"
        assert llm.parse_calls == 1


def test_python_forces_clarification_when_model_guesses_bare_city(tmp_path):
    """模型擅自把裸城市当作现居地时，确定性规则必须阻止搜索。"""

    class GuessingLocationLLM(FakeLLMClient):
        async def parse_search_draft(self, *, messages):
            return SearchPlanDraft(conditions=SearchConditions(
                current_city=LocationCondition(
                    name="杭州",
                    scope=LocationScope.CURRENT_CITY,
                )
            ))

    talent = FakeTalentSearch()
    with build_client(tmp_path, llm=GuessingLocationLLM(), talent=talent) as client:
        headers = {"X-User-Id": "user-1"}
        session_id = client.post("/api/v1/sessions", headers=headers).json()["session_id"]
        response = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            headers=headers,
            json={"client_message_id": "bare-city", "content": "找杭州的算法工程师"},
        )

        assert response.status_code == 200
        result = response.json()["result"]
        assert result["status"] == "NEEDS_CLARIFICATION"
        assert result["clarification"]["kind"] == "LOCATION_SCOPE"
        assert talent.search_calls == 0


def test_duplicate_message_does_not_repeat_search(tmp_path):
    talent = FakeTalentSearch()
    with build_client(tmp_path, talent=talent) as client:
        headers = {"X-User-Id": "user-1"}
        session_id = client.post("/api/v1/sessions", headers=headers).json()["session_id"]
        payload = {"client_message_id": "same", "content": "找Java后端，现居杭州"}
        first = client.post(f"/api/v1/sessions/{session_id}/messages", headers=headers, json=payload)
        second = client.post(f"/api/v1/sessions/{session_id}/messages", headers=headers, json=payload)
        assert first.status_code == second.status_code == 200
        assert talent.search_calls == 1


def test_session_owner_is_enforced(tmp_path):
    with build_client(tmp_path) as client:
        session_id = client.post(
            "/api/v1/sessions", headers={"X-User-Id": "owner"}
        ).json()["session_id"]
        response = client.get(
            f"/api/v1/sessions/{session_id}", headers={"X-User-Id": "other"}
        )
        assert response.status_code == 404


def test_multi_turn_patch_preserves_previous_conditions(tmp_path):
    talent = FakeTalentSearch()
    with build_client(tmp_path, talent=talent) as client:
        headers = {"X-User-Id": "user-1"}
        session_id = client.post("/api/v1/sessions", headers=headers).json()["session_id"]
        first = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            headers=headers,
            json={
                "client_message_id": "m1",
                "content": "找张三，Java后端，本科，3到5年，现居杭州",
            },
        )
        assert first.json()["result"]["plan_version"] == 1

        second = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            headers=headers,
            json={
                "client_message_id": "m2",
                "content": "只看当前职位，5年以上，改成现居上海",
            },
        )
        assert second.status_code == 200, second.text
        result = second.json()["result"]
        assert result["plan_version"] == 2
        assert result["executed_conditions"]["applicant_name"]["value"] == "张三"
        assert result["executed_conditions"]["minimum_degree"]["value"] == "本科"
        assert result["executed_conditions"]["work_years"]["minimum"] == 5
        assert talent.last_request.onlyNowPosition is True
        assert talent.last_request.livePlace == [310100]


def test_unsupported_condition_returns_card_without_search(tmp_path):
    talent = FakeTalentSearch()
    with build_client(tmp_path, talent=talent) as client:
        headers = {"X-User-Id": "user-1"}
        session_id = client.post("/api/v1/sessions", headers=headers).json()["session_id"]
        response = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            headers=headers,
            json={"client_message_id": "m1", "content": "找Java后端，必须有支付系统经验"},
        ).json()
        assert response["result"]["status"] == "UNSUPPORTED"
        assert response["result"]["clarification"]["kind"] == "UNSUPPORTED_CONDITION"
        assert talent.search_calls == 0


def test_empty_result_is_not_dependency_error(tmp_path):
    with build_client(tmp_path, talent=FakeTalentSearch(empty=True)) as client:
        headers = {"X-User-Id": "user-1"}
        session_id = client.post("/api/v1/sessions", headers=headers).json()["session_id"]
        response = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            headers=headers,
            json={"client_message_id": "m1", "content": "找Java后端，现居杭州"},
        ).json()
        assert response["result"]["status"] == "EMPTY"
        assert response["result"]["total"] == 0


def test_stale_page_reference_is_rejected(tmp_path):
    with build_client(tmp_path) as client:
        headers = {"X-User-Id": "user-1"}
        session_id = client.post("/api/v1/sessions", headers=headers).json()["session_id"]
        client.post(
            f"/api/v1/sessions/{session_id}/messages",
            headers=headers,
            json={"client_message_id": "m1", "content": "找Java后端，现居杭州"},
        )
        client.post(
            f"/api/v1/sessions/{session_id}/messages",
            headers=headers,
            json={"client_message_id": "m2", "content": "改成现居上海"},
        )
        response = client.post(
            f"/api/v1/sessions/{session_id}/pages",
            headers=headers,
            json={"reference": {"session_id": session_id, "plan_version": 1, "page": 2}},
        )
        assert response.status_code == 409


def test_entity_ambiguity_answer_uses_java_code_without_second_resolution(tmp_path):
    class AmbiguousTalentSearch(FakeTalentSearch):
        """首次解析返回两个公司，由用户通过卡片选择。"""

        async def resolve_entities(self, requests, user):
            self.resolve_calls += 1
            item = requests[0]
            return [EntityResolution(
                key=item.key,
                kind=item.kind,
                status=EntityResolutionStatus.AMBIGUOUS,
                candidates=[
                    EntityCandidate(code="company-1", label="网易集团"),
                    EntityCandidate(code="company-2", label="网易有道"),
                ],
            )]

    talent = AmbiguousTalentSearch()
    with build_client(tmp_path, talent=talent) as client:
        headers = {"X-User-Id": "user-1"}
        session_id = client.post("/api/v1/sessions", headers=headers).json()["session_id"]
        first = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            headers=headers,
            json={"client_message_id": "m1", "content": "找在网易工作过的人"},
        ).json()
        card = first["result"]["clarification"]
        assert card["kind"] == "ENTITY_AMBIGUITY"

        second = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            headers=headers,
            json={
                "client_message_id": "m2",
                "content": "网易有道",
                "clarification_answer": {
                    "question_id": card["question_id"],
                    "value": "company-2",
                },
            },
        )
        assert second.status_code == 200, second.text
        assert second.json()["result"]["status"] == "OK"
        assert talent.resolve_calls == 1
        assert talent.last_request.nowCompany[0].code == "company-2"


async def test_search_message_interrupts_model_parsing_and_replaces_run(tmp_path):
    """真正修改搜索的消息会取消旧解析，并以全部未应用消息重新执行。"""

    llm = FakeLLMClient(delay=0.08)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'interrupt.db'}",
        auto_create_schema=True,
    )
    app = create_app(settings, llm_client=llm, talent_search_client=FakeTalentSearch())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {"X-User-Id": "user-1"}
            session_id = (
                await client.post("/api/v1/sessions", headers=headers)
            ).json()["session_id"]
            first_task = asyncio.create_task(client.post(
                f"/api/v1/sessions/{session_id}/messages",
                headers=headers,
                json={"client_message_id": "m1", "content": "找 Java 后端"},
            ))
            await asyncio.sleep(0.02)
            second = await client.post(
                f"/api/v1/sessions/{session_id}/messages",
                headers=headers,
                json={
                    "client_message_id": "m2",
                    "content": "重新找张三，Java 后端，现居杭州",
                },
            )
            first = await first_task

            assert first.json()["result"]["status"] == "SUPERSEDED"
            assert second.json()["result"]["status"] == "OK"
            active = await client.get(
                f"/api/v1/sessions/{session_id}/result", headers=headers
            )
            assert active.json()["run_id"] == second.json()["result"]["run_id"]
            assert active.json()["executed_conditions"]["applicant_name"]["value"] == "张三"


async def test_casual_message_keeps_active_search_running(tmp_path):
    llm = FakeLLMClient(delay=0.05)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'casual.db'}",
        auto_create_schema=True,
    )
    app = create_app(settings, llm_client=llm, talent_search_client=FakeTalentSearch())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            headers = {"X-User-Id": "user-1"}
            session_id = (
                await client.post("/api/v1/sessions", headers=headers)
            ).json()["session_id"]
            search_task = asyncio.create_task(client.post(
                f"/api/v1/sessions/{session_id}/messages",
                headers=headers,
                json={"client_message_id": "m1", "content": "找 Java 后端，现居杭州"},
            ))
            await asyncio.sleep(0.01)
            casual = await client.post(
                f"/api/v1/sessions/{session_id}/messages",
                headers=headers,
                json={"client_message_id": "m2", "content": "哈哈哈"},
            )
            search = await search_task

            assert casual.json()["kind"] == "CHAT"
            assert search.json()["result"]["status"] == "OK"


class _BrokenLLM(FakeLLMClient):
    """模拟模型始终无法返回合法结构。"""

    async def parse_search_draft(self, *, messages):
        raise ModelOutputError("结构化输出失败")


class _FailingTalentSearch(FakeTalentSearch):
    """按指定异常模拟 Java 鉴权或依赖故障。"""

    def __init__(self, error):
        super().__init__()
        self.error = error

    async def search_candidates(self, request, user):
        raise self.error


def test_model_denied_and_dependency_failures_have_distinct_results(tmp_path):
    cases = [
        (_BrokenLLM(), FakeTalentSearch(), "MODEL_ERROR"),
        (FakeLLMClient(), _FailingTalentSearch(TalentSearchDeniedError("拒绝")), "DENIED"),
        (
            FakeLLMClient(),
            _FailingTalentSearch(TalentSearchDependencyError("不可用")),
            "DEPENDENCY_ERROR",
        ),
    ]
    for index, (llm, talent, expected) in enumerate(cases):
        case_path = tmp_path / str(index)
        case_path.mkdir()
        with build_client(case_path, llm=llm, talent=talent) as client:
            headers = {"X-User-Id": "user-1"}
            session_id = client.post("/api/v1/sessions", headers=headers).json()["session_id"]
            response = client.post(
                f"/api/v1/sessions/{session_id}/messages",
                headers=headers,
                json={"client_message_id": "m1", "content": "找 Java 后端"},
            )
            assert response.status_code == 200
            assert response.json()["result"]["status"] == expected


def test_disabled_feature_returns_service_unavailable(tmp_path):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'disabled.db'}",
        auto_create_schema=True,
        enable_agent=False,
    )
    app = create_app(
        settings,
        llm_client=FakeLLMClient(),
        talent_search_client=FakeTalentSearch(),
    )
    with TestClient(app) as client:
        headers = {"X-User-Id": "user-1"}
        session_id = client.post("/api/v1/sessions", headers=headers).json()["session_id"]
        response = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            headers=headers,
            json={"client_message_id": "m1", "content": "找 Java 后端"},
        )
        assert response.status_code == 503
        assert response.json()["code"] == "FEATURE_DISABLED"
