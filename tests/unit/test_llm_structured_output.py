"""大模型结构化输出的有限修复测试。"""

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
        return result


class _FakeModel:
    """替代 ChatOpenAI，便于只验证修复次数。"""

    def __init__(self, runnable):
        self.runnable = runnable

    def with_structured_output(self, output_type):
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
