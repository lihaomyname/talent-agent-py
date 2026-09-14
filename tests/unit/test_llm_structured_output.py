"""大模型结构化输出的有限修复测试。"""

import json
from types import SimpleNamespace

import pytest

from talent_agent_py.application.exceptions import ModelOutputError
from talent_agent_py.domain.conversation import MessageRoute
from talent_agent_py.infrastructure.clients.internal_llm import InternalLLMClient


class _FakeRunnable:
    """按顺序返回预设结果的最小可运行对象。"""

    def __init__(self, results):
        self.results = iter(results)
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        # 模拟 AIMessage：真实模型返回的 content 是 JSON 字符串。
        return SimpleNamespace(content=json.dumps(result, ensure_ascii=False))


class _FakeModel:
    """替代 ChatOpenAI，便于只验证修复次数。"""

    def __init__(self, runnable):
        self.runnable = runnable

    def bind(self, **kwargs):
        return self.runnable


def _client(results) -> tuple[InternalLLMClient, _FakeRunnable]:
    runnable = _FakeRunnable(results)
    client = InternalLLMClient.__new__(InternalLLMClient)
    client._repair_attempts = 1
    client._model = _FakeModel(runnable)
    return client, runnable


async def test_invalid_output_is_repaired_once():
    client, runnable = _client([
        {"message_type": "INVALID"},
        {
            "message_type": "SEARCH_NEW",
            "affects_active_run": True,
            "confidence": 0.9,
            "reason_code": "SEARCH_REQUEST",
        },
    ])

    result = await client._invoke_structured(
        system_prompt="测试",
        user_prompt="找 Java 开发",
        output_type=MessageRoute,
    )

    assert result.message_type.value == "SEARCH_NEW"
    assert runnable.calls == 2


async def test_invalid_output_fails_after_bounded_repair():
    client, runnable = _client([
        {"message_type": "INVALID"},
        {"message_type": "STILL_INVALID"},
    ])

    with pytest.raises(ModelOutputError):
        await client._invoke_structured(
            system_prompt="测试",
            user_prompt="找 Java 开发",
            output_type=MessageRoute,
        )
    assert runnable.calls == 2


async def test_model_network_error_is_mapped_to_domain_error():
    """模型网关异常应收敛为稳定领域错误，不能让 Run 一直处于运行中。"""

    client, _ = _client([RuntimeError("network unavailable")])

    with pytest.raises(ModelOutputError):
        await client._invoke_structured(
            system_prompt="测试",
            user_prompt="找 Java 开发",
            output_type=MessageRoute,
        )


async def test_model_timeout_has_actionable_error_message():
    """模型超时时应返回可识别原因，避免页面只显示笼统失败。"""

    client, _ = _client([TimeoutError("request timed out")])

    with pytest.raises(ModelOutputError, match="大模型请求超时"):
        await client._invoke_structured(
            system_prompt="测试",
            user_prompt="找 Java 开发",
            output_type=MessageRoute,
        )
