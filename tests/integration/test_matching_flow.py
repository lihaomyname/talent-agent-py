"""用合成资料验证匹配接口和旧搜索交接，不访问真实招聘数据。"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from talent_agent_py.application.candidate_profiles import build_candidate_profile
from talent_agent_py.domain.conversation import CandidateCard
from talent_agent_py.domain.matching import (
    CandidateEvaluation,
    CandidateProfilePage,
    EvaluationBatch,
    MatchEvidence,
    RequirementChange,
)
from talent_agent_py.main import create_app
from talent_agent_py.settings import Settings
from tests.fakes import FakeLLMClient, FakeTalentSearch


class MatchingModel:
    def __init__(self):
        self.evaluations = 0
        self.extractions = 0

    async def extract(self, content, current, version, image=None):
        self.extractions += 1
        return RequirementChange(source_text=content)

    async def evaluate(self, requirements, profiles):
        self.evaluations += 1
        return EvaluationBatch(evaluations=[CandidateEvaluation(candidate_id=p.candidate_id, evidence=[
            MatchEvidence(criterion_id=c.id, status="SUPPORTED", source_path="resumeWorkExpList.0.detail",
                          quote="枪械后坐力调优", explanation="明确描述该项工作")
            for c in requirements.required_criteria + requirements.preferences
        ]) for p in profiles])


class ProfileSearch(FakeTalentSearch):
    def __init__(self):
        super().__init__()
        self.profile_calls = 0

    async def search_candidate_profiles(self, request, user):
        self.profile_calls += 1
        profiles = []
        for index in range(10):
            cid = f"page-{request.currentPage}-{index}"
            profiles.append(build_candidate_profile(
                {"resumeWorkExpList": [{"detail": "负责枪械后坐力调优"}]},
                CandidateCard(candidate_id=cid), request.currentPage,
            ))
        return CandidateProfilePage(candidates=profiles, total=30, has_next=request.currentPage < 3)


def build_matching_client(tmp_path, model, talent, **overrides):
    return TestClient(create_app(Settings(
        _env_file=None, database_url=f"sqlite+aiosqlite:///{tmp_path / 'matching.db'}",
        auto_create_schema=True, enable_agent=True, enable_matching=True,
        **overrides,
    ), llm_client=FakeLLMClient(), talent_search_client=talent, matching_llm_client=model))


def wait_finished(client, base, run_id, headers):
    for _ in range(100):
        response = client.get(f"{base}/matches/{run_id}", headers=headers)
        assert response.status_code == 200, response.text
        if response.json()["status"] not in {"QUEUED", "RUNNING"}:
            return response.json()
        time.sleep(0.01)
    raise AssertionError("运行未结束")


def test_matching_history_continuation_and_no_authorization_search(tmp_path):
    model, talent = MatchingModel(), ProfileSearch()
    headers = {"X-User-Id": "owner"}
    with build_matching_client(tmp_path, model, talent) as client:
        sid = client.post("/api/v1/sessions", headers=headers).json()["session_id"]
        base = f"/api/v1/sessions/{sid}"
        draft = client.post(base + "/requirements", headers=headers,
                            json={"request_key": "input", "content": "找战斗策划"}).json()
        requirements = draft["requirements"]
        requirements["conditions"]["candidate_position"] = {"value": "战斗策划"}
        requirements["required_criteria"] = [{"id": "shooting", "description": "枪械调优",
                                               "source_quote": "必须枪械调优"}]
        payload = {"request_key": "confirm", "requirements": requirements}
        endpoint = base + f"/requirements/{draft['requirement_id']}/confirm"
        started = client.post(endpoint, headers=headers, json=payload)
        assert started.status_code == 200, started.text
        rid = started.json()["run_id"]
        metadata = wait_finished(client, base, rid, headers)
        assert metadata["result_count"] == 10
        assert metadata["recalled_count"] >= 10
        assert metadata["provisional_result_count"] == 0
        assert metadata["usage"]["checked_candidates"] == 10
        assert client.post(endpoint, headers=headers, json=payload).json()["run_id"] == rid
        calls = talent.profile_calls
        result = client.get(base + f"/matches/{rid}?include_results=true", headers=headers).json()
        assert len(result["candidates"]) == 10
        assert talent.profile_calls == calls
        denied = client.get(base + f"/matches/{rid}?include_results=true", headers={"X-User-Id": "other"})
        assert denied.status_code == 404
        next_payload = {"request_key": "continue"}
        next_id = client.post(base + f"/matches/{rid}/continue", headers=headers, json=next_payload).json()["run_id"]
        wait_finished(client, base, next_id, headers)
        assert client.post(base + f"/matches/{rid}/continue", headers=headers, json=next_payload).json()["run_id"] == next_id
        stale = client.post(base + f"/matches/{rid}/continue", headers=headers,
                            json={"request_key": "different-key"})
        assert stale.status_code == 409
        history = client.get(base + "/messages", headers=headers)
        assert history.status_code == 200, history.text
        assert len(history.json()) == 3
    with build_matching_client(tmp_path, model, talent) as client:
        restored = client.get(base + f"/matches/{rid}?include_results=true", headers=headers)
        assert restored.status_code == 200, restored.text
        assert len(restored.json()["candidates"]) == 10
        assert restored.json()["can_continue"] is False


def start_run(client, *, preferences=False, hard=True):
    headers = {"X-User-Id": "owner"}
    sid = client.post("/api/v1/sessions", headers=headers).json()["session_id"]
    base = f"/api/v1/sessions/{sid}"
    draft = client.post(base + "/requirements", headers=headers,
                        json={"request_key": "input", "content": "找战斗策划"}).json()
    requirements = draft["requirements"]
    requirements["conditions"]["candidate_position"] = {"value": "战斗策划"}
    if hard:
        requirements["required_criteria"] = [{"id": "hard", "description": "枪械调优", "source_quote": "必须枪械调优"}]
    if preferences:
        requirements["preferences"] = [{"id": "soft", "description": "UGC", "source_quote": "UGC优先"}]
    response = client.post(base + f"/requirements/{draft['requirement_id']}/confirm", headers=headers,
                           json={"request_key": "confirm", "requirements": requirements})
    assert response.status_code == 200, response.text
    return base, response.json()["run_id"], headers


@pytest.mark.parametrize("settings,reason,checked", [
    ({"matching_max_candidates": 3}, "CANDIDATE_LIMIT", 3),
    ({"matching_max_model_attempts": 1}, "MODEL_LIMIT", 5),
    ({"matching_max_total_candidates": 3}, "CONTEXT_LIMIT", 3),
])
def test_budget_preserves_partial_page(tmp_path, settings, reason, checked):
    model, talent = MatchingModel(), ProfileSearch()
    with build_matching_client(tmp_path, model, talent, **settings) as client:
        base, rid, headers = start_run(client)
        result = wait_finished(client, base, rid, headers)
        assert result["stop_reason"] == reason
        assert result["usage"]["checked_candidates"] == checked
        assert result["result_count"] == checked


def test_simple_confirmation_never_calls_matching_model_and_pages_work(tmp_path):
    model, talent = MatchingModel(), ProfileSearch()
    with build_matching_client(tmp_path, model, talent) as client:
        base, rid, headers = start_run(client, hard=False)
        for _ in range(100):
            run = client.get(f"/api/v1/runs/{rid}", headers=headers).json()
            if run["status"] == "SUCCEEDED":
                break
            time.sleep(0.01)
        result = client.get(base + "/result", headers=headers).json()
        assert result["plan_version"] == 1
        assert model.evaluations == 0
        assert talent.profile_calls == 0
        assert client.get(base + "/messages", headers=headers).status_code == 200
        reference = {"session_id": base.rsplit("/", 1)[1], "plan_version": 1, "page": 2}
        page = client.post(base + "/pages", headers=headers, json={"reference": reference})
        assert page.status_code == 200, page.text
        assert page.json()["result"]["page"] == 2


class SlowMatchingModel(MatchingModel):
    async def evaluate(self, requirements, profiles):
        await asyncio.sleep(1)
        return await super().evaluate(requirements, profiles)


def test_timeout_keeps_precounted_attempt_and_buffer(tmp_path):
    model, talent = SlowMatchingModel(), ProfileSearch()
    with build_matching_client(tmp_path, model, talent, matching_deadline_seconds=0.15) as client:
        base, rid, headers = start_run(client)
        result = wait_finished(client, base, rid, headers)
        assert result["stop_reason"] == "TIME_LIMIT"
        assert result["usage"]["model_attempts"] == 1
        assert result["usage"]["checked_candidates"] == 0


def test_cancel_preserves_history_and_blocks_cross_session_cancel(tmp_path):
    with build_matching_client(tmp_path, SlowMatchingModel(), ProfileSearch()) as client:
        base, rid, headers = start_run(client)
        other = client.post("/api/v1/sessions", headers=headers).json()["session_id"]
        response = client.post(f"/api/v1/sessions/{other}/matches/{rid}/cancel", headers=headers)
        assert response.status_code == 409
        assert client.post(base + f"/matches/{rid}/cancel", headers=headers).status_code == 200
        result = wait_finished(client, base, rid, headers)
        assert result["status"] == "CANCELLED"


def test_chat_status_and_stop_share_matching_control(tmp_path):
    with build_matching_client(tmp_path, SlowMatchingModel(), ProfileSearch()) as client:
        base, rid, headers = start_run(client)
        chat = client.post(base + "/messages", headers=headers,
            json={"client_message_id": "chat", "content": "你好"})
        assert chat.json()["kind"] == "CHAT"
        status = client.post(base + "/messages", headers=headers,
            json={"client_message_id": "status", "content": "进度"})
        assert status.json()["run"]["run_id"] == rid
        stopped = client.post(base + "/messages", headers=headers,
            json={"client_message_id": "stop", "content": "停止"})
        assert stopped.json()["run"]["status"] == "CANCELLED"


def test_prepare_duplicate_does_not_call_model_twice(tmp_path):
    model = MatchingModel()
    with build_matching_client(tmp_path, model, ProfileSearch()) as client:
        headers = {"X-User-Id": "owner"}
        sid = client.post("/api/v1/sessions", headers=headers).json()["session_id"]
        path = f"/api/v1/sessions/{sid}/requirements"
        payload = {"request_key": "same", "content": "找战斗策划"}
        first = client.post(path, headers=headers, json=payload).json()
        second = client.post(path, headers=headers, json=payload).json()
        assert first == second
        assert model.extractions == 1


class ExtractingModel(MatchingModel):
    async def extract(self, content, current, version, image=None):
        self.extractions += 1
        return RequirementChange.model_validate({
            "source_text": content,
            "filters_patch": {"base_plan_version": version, "operations": [
                {"operation": "REPLACE", "field": "candidate_position", "value": {"value": "战斗策划"}},
            ]},
            "criterion_edits": [{"operation": "ADD", "group": "required_criteria", "criterion_id": "hard",
                "value": {"id": "hard", "description": "枪械调优", "source_quote": "必须枪械调优"}}],
        }, strict=False)


def test_natural_language_auto_confirms_without_second_extraction(tmp_path):
    model = ExtractingModel()
    with build_matching_client(tmp_path, model, ProfileSearch()) as client:
        headers = {"X-User-Id": "owner"}
        sid = client.post("/api/v1/sessions", headers=headers).json()["session_id"]
        base = f"/api/v1/sessions/{sid}"
        response = client.post(base + "/messages", headers=headers,
            json={"client_message_id": "natural", "content": "找战斗策划，必须枪械调优"})
        assert response.status_code == 200, response.text
        rid = response.json()["matching_reference"]["run_id"]
        assert wait_finished(client, base, rid, headers)["result_count"] == 10
        assert model.extractions == 1


def test_restart_marks_unfinished_run_and_reuses_buffer(tmp_path):
    model, talent = MatchingModel(), ProfileSearch()
    with build_matching_client(tmp_path, model, talent, matching_max_model_attempts=1) as client:
        base, rid, headers = start_run(client)
        wait_finished(client, base, rid, headers)
        async def simulate_process_loss():
            async with client.app.state.matching_service.uow_factory() as uow:
                run = await uow.runs.get(rid)
                run.status = "RUNNING"
        client.portal.call(simulate_process_loss)
        calls = talent.profile_calls
    with build_matching_client(tmp_path, model, talent) as client:
        state = client.get(base + f"/matches/{rid}", headers=headers).json()
        assert state["stop_reason"] == "INTERRUPTED"
        assert talent.profile_calls == calls
        continued = client.post(base + f"/matches/{rid}/continue", headers=headers,
                                 json={"request_key": "restart-continue"}).json()["run_id"]
        result = wait_finished(client, base, continued, headers)
        assert result["result_count"] == 10
        assert talent.profile_calls == calls + 1
