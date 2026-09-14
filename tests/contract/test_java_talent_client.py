"""Java Tool HTTP 契约测试。"""

import httpx
import pytest
from pydantic import SecretStr

from talent_agent_py.application.exceptions import TalentSearchDeniedError
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
        java_requires_user_cookie=False,
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


async def test_browser_api_forwards_only_whitelisted_cookie_and_maps_page_result():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={
            "code": 200,
            "msg": None,
            "data": {
                "pages": 2,
                "total": 2,
                "lastPage": False,
                "list": [{
                    "id": "encrypted-candidate-id",
                    "applicantName": "候选人甲",
                    "nowPosition": "Java 开发",
                    "nowCompany": "示例公司",
                    "livePlaceName": "杭州",
                    "mobile": "不应进入结果",
                    "email": "private@example.com",
                    "labelList": [{"labelName": "985"}],
                }],
            },
        })

    client = httpx.AsyncClient(
        base_url="https://zhaopin.netease.com",
        transport=httpx.MockTransport(handler),
    )
    adapter = JavaTalentClient(client, Settings(
        java_base_url="https://zhaopin.netease.com",
        java_search_path="/api/eTalent/talent/list/page",
        java_requires_user_cookie=True,
    ))
    result = await adapter.search_candidates(
        TalentSearchRequest(pageSize=1),
        UserContext(
            user_id="user-1",
            auth_open_id_token=SecretStr("test-cookie-token"),
        ),
    )
    await client.aclose()

    assert captured["headers"]["cookie"] == "authOpenIdToken=test-cookie-token"
    assert result.total == 2
    assert result.has_next is True
    assert result.candidates[0].candidate_id == "encrypted-candidate-id"
    # 宽版接口包含联系方式，安全卡片必须主动丢弃这些字段。
    serialized = result.candidates[0].model_dump()
    assert "mobile" not in serialized
    assert "email" not in serialized


async def test_browser_api_rejects_request_without_user_cookie():
    client = httpx.AsyncClient(
        base_url="https://zhaopin.netease.com",
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )
    adapter = JavaTalentClient(client, Settings(
        java_base_url="https://zhaopin.netease.com",
        java_requires_user_cookie=True,
    ))
    with pytest.raises(TalentSearchDeniedError):
        await adapter.search_candidates(
            TalentSearchRequest(),
            UserContext(user_id="user-1"),
        )
    await client.aclose()
