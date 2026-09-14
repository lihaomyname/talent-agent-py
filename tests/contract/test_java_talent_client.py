"""Java Tool HTTP 契约测试。"""

import httpx

from talent_agent_py.application.ports.talent_search import TalentSearchRequest
from talent_agent_py.domain.conversation import UserContext
from talent_agent_py.infrastructure.clients.java_talent import JavaTalentClient
from talent_agent_py.settings import Settings


async def test_search_contract_preserves_v1_fields_and_server_identity():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["json"] = __import__("json").loads(request.content)
        return httpx.Response(200, json={"candidates": [], "total": 0, "has_next": False})

    client = httpx.AsyncClient(
        base_url="http://java.test",
        transport=httpx.MockTransport(handler),
    )
    adapter = JavaTalentClient(client, Settings(
        java_base_url="http://java.test",
        java_service_token="service-secret",
    ))
    response = await adapter.search_candidates(
        TalentSearchRequest(
            topDegree="06",
            workYearsMin=3,
            workYearsMax=5,
            nowPosition="Java 后端",
            onlyNowPosition=False,
            livePlace=[330100],
        ),
        UserContext(user_id="user-1", trace_id="trace-1"),
    )
    await client.aclose()

    assert response.total == 0
    assert captured["json"]["topDegree"] == "06"
    assert captured["json"]["workYearsMin"] == 3
    assert "workYears" not in captured["json"]
    assert captured["headers"]["x-effective-user-id"] == "user-1"
    assert captured["headers"]["authorization"] == "Bearer service-secret"


async def test_expected_city_uses_string_representation():
    request = TalentSearchRequest(expectWorkPlace=["330100"], livePlace=[])
    assert request.expectWorkPlace == ["330100"]
    assert request.livePlace == []
